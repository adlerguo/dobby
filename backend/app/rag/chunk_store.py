from typing import TypeAlias
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk, Chunk1024, Chunk3072

SUPPORTED_EMBEDDING_DIMS = {1024, 1536, 3072}

ChunkModel: TypeAlias = type[Chunk] | type[Chunk1024] | type[Chunk3072]


def normalize_embedding_dim(dim: int | None) -> int:
    return int(dim or 1536)


def chunk_model_for_dim(dim: int | None) -> ChunkModel:
    normalized = normalize_embedding_dim(dim)
    if normalized == 1024:
        return Chunk1024
    if normalized == 1536:
        return Chunk
    if normalized == 3072:
        return Chunk3072
    raise ValueError(f"unsupported_embedding_dim:{normalized}")


async def delete_document_chunks(
    db: AsyncSession, *, tenant_id: UUID, document_id: UUID
) -> None:
    for model in (Chunk1024, Chunk, Chunk3072):
        await db.execute(
            delete(model).where(
                model.doc_id == document_id, model.tenant_id == tenant_id
            )
        )


async def delete_kb_document_chunks(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    embedding_dim: int | None,
) -> None:
    model = chunk_model_for_dim(embedding_dim)
    await db.execute(
        delete(model).where(model.doc_id == document_id, model.tenant_id == tenant_id)
    )


async def load_document_text_from_chunks(
    db: AsyncSession, *, tenant_id: UUID, document_id: UUID
) -> str:
    parts: list[tuple[int | None, str]] = []
    for model in (Chunk1024, Chunk, Chunk3072):
        result = await db.execute(
            select(model.seq, model.content)
            .where(model.doc_id == document_id, model.tenant_id == tenant_id)
            .order_by(model.seq.asc().nulls_last(), model.created_at.asc())
        )
        parts.extend((row[0], row[1]) for row in result.all() if row[1])
    parts.sort(key=lambda item: (item[0] is None, item[0] or 0))
    return "\n\n".join(content for _, content in parts)
