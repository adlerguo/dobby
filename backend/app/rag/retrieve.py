from dataclasses import dataclass
from datetime import date
import time
from typing import Literal
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, KnowledgeBase
from app.rag.chunk_store import chunk_model_for_dim, normalize_embedding_dim
from app.rag.embeddings import embed_texts
from app.rag.text_segmenter import segment_for_search
from app.schemas import CitationOut, RetrieveOut, RetrievedChunkOut

RERANK_POOL_MULTIPLIER = 4
RERANK_MODES = {"off", "rule", "model"}


@dataclass
class Candidate:
    id: UUID
    doc_id: UUID
    doc_name: str
    seq: int | None
    content: str
    meta: dict
    doc_meta: dict | None = None
    vector_rank: int | None = None
    vector_score: float | None = None
    text_rank: int | None = None
    text_score: float | None = None
    rerank_mode: str | None = None
    rerank_score: float | None = None
    rerank_factors: dict | None = None
    rerank_fallback: bool | None = None


@dataclass(frozen=True)
class RerankConfig:
    mode: Literal["off", "rule", "model"]
    duplicate_penalty: float = 0.15
    source_weight: float = 0.05
    freshness_weight: float = 0.03
    structure_weight: float = 0.05
    page_location_weight: float = 0.02


@dataclass(frozen=True)
class RerankResult:
    candidates: list[Candidate]
    mode: str
    fallback: bool
    latency_ms: int
    input_count: int
    output_count: int


async def retrieve_chunks(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    kb_id: UUID,
    query: str,
    top_k: int,
    match_type: Literal["hybrid", "vector", "keyword"] = "hybrid",
    score_threshold: float | None = None,
    rerank_mode: Literal["off", "rule", "model"] | None = None,
    agent_rerank_config: dict | None = None,
) -> RetrieveOut | None:
    kb = await get_kb(db, tenant_id=tenant_id, kb_id=kb_id)
    if kb is None or kb.status == "archived":
        return None

    recall_k = max(top_k * 4, 20)
    vector_candidates: list[Candidate] = []
    text_candidates: list[Candidate] = []

    if match_type in {"hybrid", "vector"}:
        query_embedding = (
            await embed_texts(
                model=kb.embedding_model or "mock-embedding", texts=[query]
            )
        )[0]
        embedding_dim = normalize_embedding_dim(kb.embedding_dim)
        if len(query_embedding) != embedding_dim:
            raise ValueError("dimension_mismatch")
        vector_candidates = await vector_search(
            db, tenant_id, kb_id, query_embedding, recall_k, embedding_dim
        )
        if score_threshold and score_threshold > 0:
            vector_candidates = [
                candidate
                for candidate in vector_candidates
                if (candidate.vector_score or 0) >= score_threshold
            ]
    if match_type in {"hybrid", "keyword"}:
        text_candidates = await text_search(
            db,
            tenant_id,
            kb_id,
            query,
            recall_k,
            normalize_embedding_dim(kb.embedding_dim),
        )

    pool_k = max(top_k * RERANK_POOL_MULTIPLIER, top_k)
    pool = merge_candidates(vector_candidates, text_candidates, pool_k)
    rerank_config = resolve_rerank_config(
        kb, request_mode=rerank_mode, agent_config=agent_rerank_config
    )
    rerank_result = await rerank_candidates(
        query=query, candidates=pool, top_k=top_k, config=rerank_config
    )
    merged = rerank_result.candidates

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
            rerank_mode=candidate.rerank_mode,
            rerank_score=candidate.rerank_score,
            rerank_factors=candidate.rerank_factors,
            rerank_fallback=candidate.rerank_fallback,
            **source_fields(candidate),
            **location_fields(candidate.meta),
        )
        for candidate in merged
    ]
    citations = [
        CitationOut(
            chunk_id=candidate.id,
            doc_id=candidate.doc_id,
            doc_name=candidate.doc_name,
            seq=candidate.seq,
            content_length=len(candidate.content),
            score=hybrid_score(candidate),
            vector_score=candidate.vector_score,
            text_score=candidate.text_score,
            match_channels=match_channels(candidate),
            snippet=make_snippet(candidate.content, query),
            rerank_mode=candidate.rerank_mode,
            rerank_score=candidate.rerank_score,
            rerank_factors=candidate.rerank_factors,
            rerank_fallback=candidate.rerank_fallback,
            **source_fields(candidate),
            **location_fields(candidate.meta),
        )
        for candidate in merged
    ]
    return RetrieveOut(
        chunks=chunks,
        citations=citations,
        rerank_mode=rerank_result.mode,
        rerank_fallback=rerank_result.fallback,
        rerank_latency_ms=rerank_result.latency_ms,
        rerank_input_count=rerank_result.input_count,
        rerank_output_count=rerank_result.output_count,
    )


async def get_kb(
    db: AsyncSession, *, tenant_id: UUID, kb_id: UUID
) -> KnowledgeBase | None:
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id, KnowledgeBase.tenant_id == tenant_id
        )
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
    distance = chunk_model.embedding.cosine_distance(
        bindparam("query_embedding", type_=Vector(embedding_dim))
    )
    stmt = (
        select(
            chunk_model.id,
            chunk_model.doc_id,
            Document.name.label("doc_name"),
            Document.meta.label("doc_meta"),
            chunk_model.seq,
            chunk_model.content,
            chunk_model.meta,
            (1 - distance).label("score"),
        )
        .join(Document, Document.id == chunk_model.doc_id)
        .where(
            chunk_model.tenant_id == tenant_id,
            chunk_model.kb_id == kb_id,
            Document.version_status == "active",
            chunk_model.embedding.is_not(None),
        )
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
                doc_meta=row["doc_meta"] or {},
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
    query_tokens = segment_for_search(query)
    if not query_tokens:
        return []

    table_name = chunk_model.__tablename__
    stmt = text(
        f"""
        WITH query AS (
            SELECT plainto_tsquery('simple', :query) AS tsq
        )
        SELECT
            c.id,
            c.doc_id,
            d.name AS doc_name,
            d.meta AS doc_meta,
            c.seq,
            c.content,
            c.meta,
            ts_rank_cd(to_tsvector('simple', c.content), query.tsq)::float AS score
        FROM {table_name} c
        JOIN documents d ON d.id = c.doc_id
        CROSS JOIN query
        WHERE
            c.tenant_id = :tenant_id
            AND c.kb_id = :kb_id
            AND d.version_status = 'active'
            AND to_tsvector('simple', c.content) @@ query.tsq
        ORDER BY score DESC
        LIMIT :limit
        """
    )
    result = await db.execute(
        stmt,
        {
            "tenant_id": tenant_id,
            "kb_id": kb_id,
            "query": query_tokens,
            "limit": limit,
        },
    )
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
                doc_meta=row["doc_meta"] or {},
                text_rank=rank,
                text_score=float(row["score"] or 0),
            )
        )
    return candidates


def merge_candidates(
    vector_candidates: list[Candidate], text_candidates: list[Candidate], top_k: int
) -> list[Candidate]:
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


async def rerank_candidates(
    *,
    query: str,
    candidates: list[Candidate],
    top_k: int,
    config: RerankConfig | None = None,
) -> RerankResult:
    started = time.perf_counter()
    resolved = config or RerankConfig(mode="off")
    input_count = len(candidates)
    fallback = False

    if resolved.mode == "off":
        selected = candidates[:top_k]
        mode = "off"
    else:
        mode = resolved.mode
        if resolved.mode == "model":
            fallback = True
            mode = "rule"
        ranked = [
            apply_rule_rerank(
                candidate,
                resolved,
                requested_mode=resolved.mode,
                effective_mode=mode,
                fallback=fallback,
            )
            for candidate in candidates
        ]
        selected = sorted(
            ranked,
            key=lambda candidate: (
                candidate.rerank_score
                if candidate.rerank_score is not None
                else hybrid_score(candidate)
            ),
            reverse=True,
        )[:top_k]

    latency_ms = int((time.perf_counter() - started) * 1000)
    return RerankResult(
        candidates=selected,
        mode=mode,
        fallback=fallback,
        latency_ms=latency_ms,
        input_count=input_count,
        output_count=len(selected),
    )


def resolve_rerank_config(
    kb: KnowledgeBase,
    *,
    request_mode: str | None = None,
    agent_config: dict | None = None,
) -> RerankConfig:
    kb_config = kb.config if isinstance(getattr(kb, "config", None), dict) else {}
    kb_rerank = kb_config.get("rerank") if isinstance(kb_config.get("rerank"), dict) else {}
    agent_rerank = agent_config if isinstance(agent_config, dict) else {}
    mode = normalize_rerank_mode(
        request_mode or agent_rerank.get("mode") or kb_rerank.get("mode") or "off"
    )
    return RerankConfig(
        mode=mode,
        duplicate_penalty=coerce_weight(
            agent_rerank.get("duplicate_penalty", kb_rerank.get("duplicate_penalty")),
            0.15,
        ),
        source_weight=coerce_weight(
            agent_rerank.get("source_weight", kb_rerank.get("source_weight")),
            0.05,
        ),
        freshness_weight=coerce_weight(
            agent_rerank.get("freshness_weight", kb_rerank.get("freshness_weight")),
            0.03,
        ),
        structure_weight=coerce_weight(
            agent_rerank.get("structure_weight", kb_rerank.get("structure_weight")),
            0.05,
        ),
        page_location_weight=coerce_weight(
            agent_rerank.get(
                "page_location_weight", kb_rerank.get("page_location_weight")
            ),
            0.02,
        ),
    )


def normalize_rerank_mode(value: object) -> Literal["off", "rule", "model"]:
    mode = str(value or "off").strip().lower()
    return mode if mode in RERANK_MODES else "off"


def coerce_weight(value: object, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(min(number, 1.0), 0.0)


def apply_rule_rerank(
    candidate: Candidate,
    config: RerankConfig,
    *,
    requested_mode: str,
    effective_mode: str,
    fallback: bool,
) -> Candidate:
    meta = candidate.meta or {}
    base = hybrid_score(candidate)
    structure_bonus = base * config.structure_weight if has_structure_meta(meta) else 0.0
    page_bonus = (
        base * config.page_location_weight if meta.get("page_start") is not None else 0.0
    )
    source_bonus = base * source_bonus_ratio_for_candidate(
        candidate, config.source_weight
    )
    freshness_bonus = base * freshness_bonus_ratio_for_candidate(
        candidate, config.freshness_weight
    )
    duplicate_penalty = (
        base * config.duplicate_penalty if bool(meta.get("duplicate_in_document")) else 0.0
    )
    final = round(
        base
        + structure_bonus
        + page_bonus
        + source_bonus
        + freshness_bonus
        - duplicate_penalty,
        6,
    )
    factors = {
        "base_score": base,
        "structure_bonus": round(structure_bonus, 6),
        "page_location_bonus": round(page_bonus, 6),
        "source_bonus": round(source_bonus, 6),
        "freshness_bonus": round(freshness_bonus, 6),
        "duplicate_penalty": round(duplicate_penalty, 6),
    }
    if fallback:
        factors["fallback_reason"] = "model_rerank_not_configured"
    candidate.rerank_mode = effective_mode
    candidate.rerank_score = final
    candidate.rerank_factors = factors
    candidate.rerank_fallback = fallback
    return candidate


def has_structure_meta(meta: dict) -> bool:
    return any(
        bool(meta.get(key))
        for key in ("heading_path", "title_path", "section_no", "section_title")
    )


def source_bonus_ratio_for_candidate(candidate: Candidate, weight: float) -> float:
    fields = source_fields(candidate)
    signals = [
        bool(fields.get("source_name")),
        bool(fields.get("version_label")),
        bool(fields.get("tags")),
    ]
    if not any(signals):
        return 0.0
    return weight * (sum(1 for signal in signals if signal) / len(signals))


def freshness_bonus_ratio_for_candidate(candidate: Candidate, weight: float) -> float:
    if weight <= 0:
        return 0.0
    published_at = source_fields(candidate).get("published_at")
    if not published_at:
        return 0.0
    try:
        published = date.fromisoformat(str(published_at)[:10])
    except ValueError:
        return 0.0
    age_days = max((date.today() - published).days, 0)
    if age_days <= 365:
        return weight
    if age_days <= 365 * 3:
        return weight * 0.5
    return 0.0


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


def source_fields(candidate: Candidate) -> dict:
    chunk_meta = candidate.meta or {}
    doc_source = {}
    if isinstance(candidate.doc_meta, dict) and isinstance(
        candidate.doc_meta.get("source"), dict
    ):
        doc_source = candidate.doc_meta["source"]

    def pick(key: str, default=None):
        if key in chunk_meta:
            return chunk_meta.get(key)
        return doc_source.get(key, default)

    tags = pick("tags", [])
    return {
        "source_name": pick("source_name"),
        "source_type": pick("source_type"),
        "tags": tags if isinstance(tags, list) else [],
        "version_label": pick("version_label"),
        "published_at": pick("published_at"),
    }


def location_fields(meta: dict | None) -> dict:
    meta = meta or {}
    return {
        "page_start": int_or_none(meta.get("page_start")),
        "page_end": int_or_none(meta.get("page_end")),
        "paragraph_start": int_or_none(meta.get("paragraph_start")),
        "paragraph_end": int_or_none(meta.get("paragraph_end")),
        "block_start": int_or_none(meta.get("block_start")),
        "block_end": int_or_none(meta.get("block_end")),
    }


def int_or_none(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
