from functools import partial
from uuid import UUID

from anyio import to_thread
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import download_object
from app.models import Chunk, Document, KnowledgeBase
from app.rag.chunking import chunk_text
from app.rag.embeddings import embed_texts
from app.rag.parsers import parse_document_bytes


async def ingest_document(db: AsyncSession, document_id: UUID, *, force: bool = False) -> None:
    result = await db.execute(
        select(Document, KnowledgeBase)
        .join(KnowledgeBase, KnowledgeBase.id == Document.kb_id)
        .where(Document.id == document_id)
    )
    row = result.first()
    if row is None:
        return

    document, kb = row
    if not force and document.parse_status not in {"pending", "failed"}:
        return

    await mark_document(db, document, "parsing", task_status="running")

    try:
        text = await load_document_text(db, document, force=force)
        chunk_size = int((kb.config or {}).get("chunk_size", 800))
        overlap = int((kb.config or {}).get("overlap", 80))
        chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
        if not chunks:
            raise ValueError("document_has_no_text")

        embeddings = await embed_texts(
            model=kb.embedding_model or "mock-embedding",
            texts=[chunk.content for chunk in chunks],
        )
        if len(embeddings) != len(chunks):
            raise ValueError("embedding_count_mismatch")
        if any(len(embedding) != 1536 for embedding in embeddings):
            raise ValueError("dimension_mismatch")

        await db.execute(delete(Chunk).where(Chunk.doc_id == document.id, Chunk.tenant_id == document.tenant_id))
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            db.add(
                Chunk(
                    tenant_id=document.tenant_id,
                    kb_id=document.kb_id,
                    doc_id=document.id,
                    seq=chunk.seq,
                    content=chunk.content,
                    tokens=len(chunk.content.split()),
                    meta=chunk.meta,
                    embedding=embedding,
                )
            )

        meta = dict(document.meta or {})
        meta["ingest_task"] = {"status": "done", "chunk_count": len(chunks)}
        document.meta = meta
        document.parse_status = "done"
        await db.commit()
    except Exception as exc:
        meta = dict(document.meta or {})
        meta["ingest_task"] = {"status": "failed", "error": str(exc)}
        document.meta = meta
        document.parse_status = "failed"
        await db.commit()


async def mark_document(db: AsyncSession, document: Document, parse_status: str, *, task_status: str) -> None:
    meta = dict(document.meta or {})
    meta["ingest_task"] = {"status": task_status}
    document.meta = meta
    document.parse_status = parse_status
    await db.commit()


async def load_document_text(db: AsyncSession, document: Document, *, force: bool) -> str:
    try:
        content = await to_thread.run_sync(partial(download_object, document.source_uri))
        return parse_document_bytes(content=content, mime=document.mime, filename=document.name)
    except Exception:
        if not force:
            raise

    result = await db.execute(
        select(Chunk.content)
        .where(Chunk.doc_id == document.id, Chunk.tenant_id == document.tenant_id)
        .order_by(Chunk.seq.asc().nulls_last(), Chunk.created_at.asc())
    )
    text = "\n\n".join(row[0] for row in result.all() if row[0])
    if not text.strip():
        raise ValueError("source_document_unavailable")
    return text
