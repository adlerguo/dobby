import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.rag.retrieve import (
    Candidate,
    RerankConfig,
    apply_rule_rerank,
    rerank_candidates,
    resolve_rerank_config,
)


def run_async(awaitable):
    return asyncio.run(awaitable)


def make_candidate(*, meta=None, doc_meta=None, vector_rank=1, text_rank=None) -> Candidate:
    return Candidate(
        id=uuid4(),
        doc_id=uuid4(),
        doc_name="doc.md",
        seq=1,
        content="alpha beta",
        meta=meta or {},
        doc_meta=doc_meta or {},
        vector_rank=vector_rank,
        vector_score=0.9,
        text_rank=text_rank,
        text_score=0.8 if text_rank is not None else None,
    )


def test_off_mode_preserves_original_order() -> None:
    candidates = [
        make_candidate(vector_rank=1),
        make_candidate(vector_rank=2),
        make_candidate(vector_rank=3),
    ]

    result = run_async(
        rerank_candidates(
            query="alpha",
            candidates=candidates,
            top_k=2,
            config=RerankConfig(mode="off"),
        )
    )

    assert result.mode == "off"
    assert [candidate.id for candidate in result.candidates] == [
        candidate.id for candidate in candidates[:2]
    ]
    assert all(candidate.rerank_score is None for candidate in result.candidates)


def test_rule_mode_rewards_structure_source_and_page() -> None:
    plain = make_candidate(vector_rank=1)
    enriched = make_candidate(
        meta={
            "heading_path": ["Root"],
            "page_start": 1,
            "source_name": "制度",
            "version_label": "v2",
            "tags": ["HR"],
            "published_at": "2026-01-01",
        },
        vector_rank=2,
    )

    result = run_async(
        rerank_candidates(
            query="alpha",
            candidates=[plain, enriched],
            top_k=2,
            config=RerankConfig(mode="rule"),
        )
    )

    assert result.mode == "rule"
    assert result.candidates[0].id == enriched.id
    assert enriched.rerank_score is not None
    assert enriched.rerank_factors["structure_bonus"] > 0
    assert enriched.rerank_factors["source_bonus"] > 0
    assert enriched.rerank_factors["page_location_bonus"] > 0


def test_duplicate_chunk_gets_penalty() -> None:
    candidate = make_candidate(meta={"duplicate_in_document": True})

    reranked = apply_rule_rerank(
        candidate,
        RerankConfig(mode="rule"),
        requested_mode="rule",
        effective_mode="rule",
        fallback=False,
    )

    assert reranked.rerank_factors["duplicate_penalty"] > 0
    assert reranked.rerank_score < reranked.rerank_factors["base_score"]


def test_missing_meta_does_not_raise() -> None:
    candidate = make_candidate(meta={})

    reranked = apply_rule_rerank(
        candidate,
        RerankConfig(mode="rule"),
        requested_mode="rule",
        effective_mode="rule",
        fallback=False,
    )

    assert reranked.rerank_score is not None
    assert reranked.rerank_factors["structure_bonus"] == 0


def test_model_mode_falls_back_to_rule() -> None:
    candidate = make_candidate(meta={"section_no": "1", "page_start": 1})

    result = run_async(
        rerank_candidates(
            query="alpha",
            candidates=[candidate],
            top_k=1,
            config=RerankConfig(mode="model"),
        )
    )

    assert result.mode == "rule"
    assert result.fallback is True
    assert result.candidates[0].rerank_fallback is True
    assert (
        result.candidates[0].rerank_factors["fallback_reason"]
        == "model_rerank_not_configured"
    )


def test_resolve_rerank_config_precedence() -> None:
    kb = SimpleNamespace(
        config={
            "rerank": {
                "mode": "rule",
                "duplicate_penalty": 0.2,
            }
        }
    )

    assert resolve_rerank_config(kb).mode == "rule"
    assert resolve_rerank_config(kb, agent_config={"mode": "off"}).mode == "off"
    assert (
        resolve_rerank_config(kb, request_mode="model", agent_config={"mode": "off"}).mode
        == "model"
    )
