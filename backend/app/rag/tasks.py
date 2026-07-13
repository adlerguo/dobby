from uuid import UUID

from app.core.database import SessionLocal
from app.rag.ingest import ingest_document


async def enqueue_parse_document(document_id: UUID) -> None:
    async with SessionLocal() as db:
        await ingest_document(db, document_id)


async def enqueue_reindex_document(document_id: UUID) -> None:
    async with SessionLocal() as db:
        await ingest_document(db, document_id, force=True)
