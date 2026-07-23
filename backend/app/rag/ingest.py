from functools import partial
import logging
from uuid import UUID

from anyio import to_thread
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import download_object
from app.rag.chunking import chunk_text
from app.rag.chunk_store import (
    chunk_model_for_dim,
    delete_kb_document_chunks,
    load_document_text_from_chunks,
)
from app.rag.embeddings import embed_texts
from app.rag.parsers import parse_document_bytes
from app.models import Document, KnowledgeBase

logger = logging.getLogger(__name__)


async def ingest_document(
    db: AsyncSession, document_id: UUID, *, force: bool = False
) -> None:
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
        meta["ingest_task"] = {
            "status": "done",
            "chunk_count": len(chunks),
            "embedding_dim": embedding_dim,
        }
        document.meta = meta
        document.parse_status = "done"
        await db.commit()
    except Exception as exc:
        error_payload = ingest_error_payload(exc)
        logger.warning(
            "document_ingest_failed document_id=%s stage=%s error_code=%s",
            document.id,
            error_payload["stage"],
            error_payload["error_code"],
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        meta = dict(document.meta or {})
        meta["ingest_task"] = {"status": "failed", "error": error_payload}
        document.meta = meta
        document.parse_status = "failed"
        await db.commit()


async def mark_document(
    db: AsyncSession, document: Document, parse_status: str, *, task_status: str
) -> None:
    meta = dict(document.meta or {})
    meta["ingest_task"] = {"status": task_status}
    document.meta = meta
    document.parse_status = parse_status
    await db.commit()


async def load_document_text(
    db: AsyncSession, document: Document, *, force: bool
) -> str:
    try:
        content = await to_thread.run_sync(
            partial(download_object, document.source_uri)
        )
    except Exception:
        if not force:
            raise ValueError("storage_download_failed")
    else:
        try:
            return parse_document_bytes(
                content=content, mime=document.mime, filename=document.name
            )
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("parser_failed") from exc

    text = await load_document_text_from_chunks(
        db, tenant_id=document.tenant_id, document_id=document.id
    )
    if not text.strip():
        raise ValueError("source_document_unavailable")
    return text


def ingest_error_payload(exc: Exception) -> dict:
    raw_code = str(exc)
    code_map = {
        "unsupported_document_type": ("parse", "unsupported_document_type", False),
        "document_has_no_text": ("chunk", "document_has_no_text", False),
        "parser_failed": ("parse", "parser_failed", True),
        "storage_download_failed": ("storage", "storage_download_failed", True),
        "source_document_unavailable": ("storage", "storage_download_failed", True),
        "no_active_model_channel": ("embedding", "embedding_model_unavailable", True),
        "maas_call_failed": ("embedding", "embedding_model_unavailable", True),
        "maas_timeout": ("embedding", "embedding_model_unavailable", True),
        "embedding_count_mismatch": ("embedding", "embedding_model_unavailable", True),
        "dimension_mismatch": ("embedding", "embedding_model_unavailable", True),
    }
    stage, error_code, retryable = code_map.get(raw_code, ("unknown", "unknown", True))
    return {
        "stage": stage,
        "error_code": error_code,
        "error_message": raw_code or exc.__class__.__name__,
        "retryable": retryable,
    }
