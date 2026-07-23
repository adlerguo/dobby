import asyncio
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("MAAS_ADMIN_TOKEN", "test-token")

from app.rag import retrieve


TENANT_ID = uuid4()
KB_ID = uuid4()


class FakeScalarResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDB:
    async def execute(self, stmt, params=None):
        return FakeScalarResult(
            SimpleNamespace(
                status="active", embedding_model="mock-embedding", embedding_dim=1536
            )
        )


def run_async(awaitable):
    return asyncio.run(awaitable)


def make_candidate(*, vector_rank=None, text_rank=None) -> retrieve.Candidate:
    return retrieve.Candidate(
        id=uuid4(),
        doc_id=uuid4(),
        doc_name="doc",
        seq=1,
        content="alpha beta gamma",
        meta={},
        vector_rank=vector_rank,
        vector_score=0.9 if vector_rank is not None else None,
        text_rank=text_rank,
        text_score=0.8 if text_rank is not None else None,
    )


def test_retrieve_chunks_rerank_hook_is_pass_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vector_candidates = [
        make_candidate(vector_rank=1),
        make_candidate(vector_rank=2),
        make_candidate(vector_rank=3),
        make_candidate(vector_rank=4),
    ]
    text_candidates = [
        retrieve.Candidate(
            id=vector_candidates[2].id,
            doc_id=vector_candidates[2].doc_id,
            doc_name=vector_candidates[2].doc_name,
            seq=vector_candidates[2].seq,
            content=vector_candidates[2].content,
            meta={},
            text_rank=1,
            text_score=0.95,
        ),
        make_candidate(text_rank=2),
    ]
    top_k = 3
    expected = retrieve.merge_candidates(vector_candidates, text_candidates, top_k)
    calls: list[tuple[str, int, int]] = []

    async def fake_embed_texts(*, model, texts):
        return [[0.0] * 1536]

    async def fake_vector_search(
        db, tenant_id, kb_id, query_embedding, limit, embedding_dim
    ):
        return vector_candidates

    async def fake_text_search(db, tenant_id, kb_id, query, limit, embedding_dim):
        return text_candidates

    async def tracking_rerank_candidates(*, query, candidates, top_k):
        calls.append((query, len(candidates), top_k))
        return await original_rerank(query=query, candidates=candidates, top_k=top_k)

    original_rerank = retrieve.rerank_candidates
    monkeypatch.setattr(retrieve, "embed_texts", fake_embed_texts)
    monkeypatch.setattr(retrieve, "vector_search", fake_vector_search)
    monkeypatch.setattr(retrieve, "text_search", fake_text_search)
    monkeypatch.setattr(retrieve, "rerank_candidates", tracking_rerank_candidates)

    result = run_async(
        retrieve.retrieve_chunks(
            FakeDB(),
            tenant_id=TENANT_ID,
            kb_id=KB_ID,
            query="alpha",
            top_k=top_k,
            match_type="hybrid",
        )
    )

    assert result is not None
    assert [chunk.id for chunk in result.chunks] == [
        candidate.id for candidate in expected
    ]
    assert [citation.chunk_id for citation in result.citations] == [
        candidate.id for candidate in expected
    ]
    assert [chunk.score for chunk in result.chunks] == [
        retrieve.hybrid_score(candidate) for candidate in expected
    ]
    assert calls == [
        (
            "alpha",
            len(
                retrieve.merge_candidates(vector_candidates, text_candidates, top_k * 4)
            ),
            top_k,
        )
    ]
