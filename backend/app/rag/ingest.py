from functools import partial
from uuid import UUID

from anyio import to_thread
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import download_object
from app.rag.chunking import chunk_text
from app.rag.chunk_store import chunk_model_for_dim, delete_kb_document_chunks, load_document_text_from_chunks
from app.rag.embeddings import embed_texts
from app.rag.parsers import parse_document_bytes
from app.models import Document, KnowledgeBase


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
        embedding_dim = int(kb.embedding_dim or 1536)
        if any(len(embedding) != embedding_dim for embedding in embeddings):
            raise ValueError("dimension_mismatch")

        chunk_model = chunk_model_for_dim(embedding_dim)
        await delete_kb_document_chunks(
            db,
            tenant_id=document.tenant_id,
            document_id=document.id,
            embedding_dim=embedding_dim,
        )
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            db.add(
                chunk_model(
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
        meta["ingest_task"] = {"status": "done", "chunk_count": len(chunks), "embedding_dim": embedding_dim}
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

    text = await load_document_text_from_chunks(db, tenant_id=document.tenant_id, document_id=document.id)
    if not text.strip():
        raise ValueError("source_document_unavailable")
    return text
