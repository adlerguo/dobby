from dataclasses import dataclass
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, bindparam, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk, Document, KnowledgeBase
from app.rag.embeddings import embed_texts
from app.schemas import CitationOut, RetrieveOut, RetrievedChunkOut


@dataclass
class Candidate:
    id: UUID
    doc_id: UUID
    doc_name: str
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
) -> RetrieveOut | None:
    kb = await get_kb(db, tenant_id=tenant_id, kb_id=kb_id)
    if kb is None or kb.status == "archived":
        return None

    query_embedding = (await embed_texts(model=kb.embedding_model or "mock-embedding", texts=[query]))[0]
    recall_k = max(top_k * 4, 20)
    vector_candidates = await vector_search(db, tenant_id, kb_id, query_embedding, recall_k)
    text_candidates = await text_search(db, tenant_id, kb_id, query, recall_k)
    merged = merge_candidates(vector_candidates, text_candidates, top_k)

    chunks = [
        RetrievedChunkOut(
            id=candidate.id,
            doc_id=candidate.doc_id,
            content=candidate.content,
            score=hybrid_score(candidate),
            vector_score=candidate.vector_score,
            text_score=candidate.text_score,
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
) -> list[Candidate]:
    distance = Chunk.embedding.cosine_distance(bindparam("query_embedding", type_=Vector(1536)))
    stmt = (
        select(
            Chunk.id,
            Chunk.doc_id,
            Document.name.label("doc_name"),
            Chunk.content,
            Chunk.meta,
            (1 - distance).label("score"),
        )
        .join(Document, Document.id == Chunk.doc_id)
        .where(Chunk.tenant_id == tenant_id, Chunk.kb_id == kb_id, Chunk.embedding.is_not(None))
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
                content=row["content"],
                meta=row["meta"] or {},
                vector_rank=rank,
                vector_score=float(row["score"]),
            )
        )
    return candidates


async def text_search(db: AsyncSession, tenant_id: UUID, kb_id: UUID, query: str, limit: int) -> list[Candidate]:
    ts_query = func.plainto_tsquery("simple", query)
    ts_vector = func.to_tsvector("simple", Chunk.content)
    score = func.ts_rank_cd(ts_vector, ts_query).cast(Float)
    stmt = (
        select(
            Chunk.id,
            Chunk.doc_id,
            Document.name.label("doc_name"),
            Chunk.content,
            Chunk.meta,
            score.label("score"),
        )
        .join(Document, Document.id == Chunk.doc_id)
        .where(
            Chunk.tenant_id == tenant_id,
            Chunk.kb_id == kb_id,
            text("to_tsvector('simple', chunks.content) @@ plainto_tsquery('simple', :query)"),
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
