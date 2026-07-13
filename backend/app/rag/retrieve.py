from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, bindparam, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, KnowledgeBase
from app.rag.chunk_store import chunk_model_for_dim, normalize_embedding_dim
from app.rag.embeddings import embed_texts
from app.schemas import CitationOut, RetrieveOut, RetrievedChunkOut


@dataclass
class Candidate:
    id: UUID
    doc_id: UUID
    doc_name: str
    seq: int | None
    content: str
    meta: dict
    vector_rank: int | None = None
    vector_score: float | None = None
    text_rank: int | None = None
    text_score: float | None = None


async def retrieve_chunks(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    kb_id: UUID,
    query: str,
    top_k: int,
    match_type: Literal["hybrid", "vector", "keyword"] = "hybrid",
    score_threshold: float | None = None,
) -> RetrieveOut | None:
    kb = await get_kb(db, tenant_id=tenant_id, kb_id=kb_id)
    if kb is None or kb.status == "archived":
        return None

    recall_k = max(top_k * 4, 20)
    vector_candidates: list[Candidate] = []
    text_candidates: list[Candidate] = []

    if match_type in {"hybrid", "vector"}:
        query_embedding = (await embed_texts(model=kb.embedding_model or "mock-embedding", texts=[query]))[0]
        embedding_dim = normalize_embedding_dim(kb.embedding_dim)
        if len(query_embedding) != embedding_dim:
            raise ValueError("dimension_mismatch")
        vector_candidates = await vector_search(db, tenant_id, kb_id, query_embedding, recall_k, embedding_dim)
        if score_threshold and score_threshold > 0:
            vector_candidates = [
                candidate for candidate in vector_candidates if (candidate.vector_score or 0) >= score_threshold
            ]
    if match_type in {"hybrid", "keyword"}:
        text_candidates = await text_search(db, tenant_id, kb_id, query, recall_k, normalize_embedding_dim(kb.embedding_dim))

    merged = merge_candidates(vector_candidates, text_candidates, top_k)

    chunks = [
        RetrievedChunkOut(
            id=candidate.id,
            doc_id=candidate.doc_id,
            doc_name=candidate.doc_name,
            seq=candidate.seq,
            content=candidate.content,
            content_length=len(candidate.content),
            score=hybrid_score(candidate),
            vector_score=candidate.vector_score,
            text_score=candidate.text_score,
            match_channels=match_channels(candidate),
            meta=candidate.meta or {},
        )
        for candidate in merged
    ]
    citations = [
        CitationOut(
            chunk_id=candidate.id,
            doc_id=candidate.doc_id,
            doc_name=candidate.doc_name,
            score=hybrid_score(candidate),
            snippet=make_snippet(candidate.content, query),
        )
        for candidate in merged
    ]
    return RetrieveOut(chunks=chunks, citations=citations)


async def get_kb(db: AsyncSession, *, tenant_id: UUID, kb_id: UUID) -> KnowledgeBase | None:
    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def vector_search(
    db: AsyncSession,
    tenant_id: UUID,
    kb_id: UUID,
    query_embedding: list[float],
    limit: int,
    embedding_dim: int,
) -> list[Candidate]:
    chunk_model = chunk_model_for_dim(embedding_dim)
    distance = chunk_model.embedding.cosine_distance(bindparam("query_embedding", type_=Vector(embedding_dim)))
    stmt = (
        select(
            chunk_model.id,
            chunk_model.doc_id,
            Document.name.label("doc_name"),
            chunk_model.seq,
            chunk_model.content,
            chunk_model.meta,
            (1 - distance).label("score"),
        )
        .join(Document, Document.id == chunk_model.doc_id)
        .where(chunk_model.tenant_id == tenant_id, chunk_model.kb_id == kb_id, chunk_model.embedding.is_not(None))
        .order_by(distance)
        .limit(limit)
    )
    result = await db.execute(stmt, {"query_embedding": query_embedding})
    candidates: list[Candidate] = []
    for rank, row in enumerate(result.mappings().all(), start=1):
        candidates.append(
            Candidate(
                id=row["id"],
                doc_id=row["doc_id"],
                doc_name=row["doc_name"],
                seq=row["seq"],
                content=row["content"],
                meta=row["meta"] or {},
                vector_rank=rank,
                vector_score=float(row["score"]),
            )
        )
    return candidates


async def text_search(
    db: AsyncSession,
    tenant_id: UUID,
    kb_id: UUID,
    query: str,
    limit: int,
    embedding_dim: int,
) -> list[Candidate]:
    chunk_model = chunk_model_for_dim(embedding_dim)
    ts_query = func.plainto_tsquery("simple", query)
    ts_vector = func.to_tsvector("simple", chunk_model.content)
    score = func.ts_rank_cd(ts_vector, ts_query).cast(Float)
    stmt = (
        select(
            chunk_model.id,
            chunk_model.doc_id,
            Document.name.label("doc_name"),
            chunk_model.seq,
            chunk_model.content,
            chunk_model.meta,
            score.label("score"),
        )
        .join(Document, Document.id == chunk_model.doc_id)
        .where(
            chunk_model.tenant_id == tenant_id,
            chunk_model.kb_id == kb_id,
            text(f"to_tsvector('simple', {chunk_model.__tablename__}.content) @@ plainto_tsquery('simple', :query)"),
        )
        .order_by(score.desc())
        .limit(limit)
    )
    result = await db.execute(stmt, {"query": query})
    candidates: list[Candidate] = []
    for rank, row in enumerate(result.mappings().all(), start=1):
        candidates.append(
            Candidate(
                id=row["id"],
                doc_id=row["doc_id"],
                doc_name=row["doc_name"],
                seq=row["seq"],
                content=row["content"],
                meta=row["meta"] or {},
                text_rank=rank,
                text_score=float(row["score"] or 0),
            )
        )
    return candidates


def merge_candidates(vector_candidates: list[Candidate], text_candidates: list[Candidate], top_k: int) -> list[Candidate]:
    by_id: dict[UUID, Candidate] = {}
    for candidate in vector_candidates:
        by_id[candidate.id] = candidate
    for candidate in text_candidates:
        existing = by_id.get(candidate.id)
        if existing is None:
            by_id[candidate.id] = candidate
            continue
        existing.text_rank = candidate.text_rank
        existing.text_score = candidate.text_score

    return sorted(by_id.values(), key=hybrid_score, reverse=True)[:top_k]


def hybrid_score(candidate: Candidate) -> float:
    score = 0.0
    if candidate.vector_rank is not None:
        score += 1 / (60 + candidate.vector_rank)
    if candidate.text_rank is not None:
        score += 1 / (60 + candidate.text_rank)
    return round(score, 6)


def match_channels(candidate: Candidate) -> list[Literal["vector", "keyword"]]:
    channels: list[Literal["vector", "keyword"]] = []
    if candidate.vector_rank is not None:
        channels.append("vector")
    if candidate.text_rank is not None:
        channels.append("keyword")
    return channels


def make_snippet(content: str, query: str, size: int = 160) -> str:
    normalized = " ".join(content.split())
    terms = [term for term in query.split() if term]
    lower = normalized.lower()
    hit = -1
    for term in terms:
        hit = lower.find(term.lower())
        if hit >= 0:
            break
    if hit < 0:
        return normalized[:size]
    start = max(hit - size // 3, 0)
    return normalized[start : start + size]
