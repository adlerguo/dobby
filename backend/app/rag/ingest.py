from functools import partial
from dataclasses import replace
import logging
from uuid import UUID

from anyio import to_thread
from sqlalchemy import select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import download_object
from app.rag.chunking import TextBlock, chunk_document_blocks
from app.rag.chunk_store import (
    chunk_model_for_dim,
    delete_kb_document_chunks,
    load_document_text_from_chunks,
)
from app.rag.cleaning import CleanTextResult, clean_text
from app.rag.dedupe import chunk_content_hash, text_fingerprint
from app.rag.embeddings import embed_texts
from app.rag.parsers import ParsedDocument, parse_document_blocks
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
        parsed_document = await load_parsed_document(db, document, force=force)
        raw_text = parsed_document.text
        cleaning_config = (kb.config or {}).get("cleaning")
        cleaning_result = clean_text(raw_text, cleaning_config)
        located_blocks = clean_located_blocks(
            parsed_document.blocks,
            cleaning_result.text,
            cleaning_config,
        )
        located_text = "\n\n".join(block.text for block in located_blocks)
        if located_text:
            cleaning_result = replace(
                cleaning_result,
                text=located_text,
                cleaned_chars=len(located_text),
                cleaned_lines=len(located_text.splitlines()),
            )
        text = cleaning_result.text
        fingerprint = text_fingerprint(text)
        text_duplicate = await find_duplicate_text_fingerprint(
            db,
            tenant_id=document.tenant_id,
            kb_id=document.kb_id,
            fingerprint=fingerprint,
            document_id=document.id,
        )
        chunking_config = resolve_chunking_config(kb.config or {})
        chunk_blocks = located_blocks or [TextBlock(text=text, block_index=1)]
        chunks = chunk_document_blocks(
            chunk_blocks,
            strategy=chunking_config["strategy"],
            chunk_size=chunking_config["chunk_size"],
            overlap=chunking_config["overlap"],
        )
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
        chunk_hashes_seen: set[str] = set()
        source_meta = document_source_meta(document)
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            content_hash = chunk_content_hash(chunk.content)
            chunk_meta = build_chunk_ingest_meta(
                chunk.meta,
                content_hash=content_hash,
                cleaning_version=cleaning_result.cleaning_version,
                duplicate_in_document=content_hash in chunk_hashes_seen,
                source_meta=source_meta,
            )
            chunk_hashes_seen.add(content_hash)
            db.add(
                chunk_model(
                    tenant_id=document.tenant_id,
                    kb_id=document.kb_id,
                    doc_id=document.id,
                    seq=chunk.seq,
                    content=chunk.content,
                    tokens=len(chunk.content.split()),
                    meta=chunk_meta,
                    embedding=embedding,
                )
            )

        meta = build_ingest_success_meta(
            document_meta=document.meta,
            cleaning_result=cleaning_result,
            fingerprint=fingerprint,
            text_duplicate=text_duplicate,
            chunk_count=len(chunks),
            embedding_dim=embedding_dim,
            chunk_strategy=str(chunks[0].meta.get("chunk_strategy") or "simple"),
            chunk_method=str(chunks[0].meta.get("chunk_method") or "simple_window"),
            fallback_chunking=any(
                bool(chunk.meta.get("fallback_chunking")) for chunk in chunks
            ),
            block_count=len(parsed_document.blocks),
            located_chunk_count=sum(1 for chunk in chunks if is_chunk_located(chunk.meta)),
            page_located_chunk_count=sum(
                1 for chunk in chunks if chunk.meta.get("page_start") is not None
            ),
        )
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


async def load_parsed_document(
    db: AsyncSession, document: Document, *, force: bool
) -> ParsedDocument:
    try:
        content = await to_thread.run_sync(
            partial(download_object, document.source_uri)
        )
    except Exception:
        if not force:
            raise ValueError("storage_download_failed")
    else:
        try:
            return parse_document_blocks(
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
    return ParsedDocument(
        text=text,
        blocks=[TextBlock(text=text, block_index=1)],
    )


async def load_document_text(
    db: AsyncSession, document: Document, *, force: bool
) -> str:
    return (await load_parsed_document(db, document, force=force)).text


async def find_duplicate_text_fingerprint(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    kb_id: UUID,
    fingerprint: str,
    document_id: UUID,
) -> dict | None:
    result = await db.execute(
        sql_text(
            """
            SELECT id, name
            FROM documents
            WHERE tenant_id = :tenant_id
                AND kb_id = :kb_id
                AND id != :document_id
                AND meta ->> 'text_fingerprint' = :fingerprint
            ORDER BY created_at ASC
            LIMIT 1
            """
        ),
        {
            "tenant_id": tenant_id,
            "kb_id": kb_id,
            "document_id": document_id,
            "fingerprint": fingerprint,
        },
    )
    row = result.mappings().first()
    return dict(row) if row else None


def build_ingest_success_meta(
    *,
    document_meta: dict | None,
    cleaning_result: CleanTextResult,
    fingerprint: str,
    text_duplicate: dict | None,
    chunk_count: int,
    embedding_dim: int,
    chunk_strategy: str = "simple",
    chunk_method: str = "simple_window",
    fallback_chunking: bool = False,
    block_count: int = 0,
    located_chunk_count: int = 0,
    page_located_chunk_count: int = 0,
) -> dict:
    meta = dict(document_meta or {})
    meta["text_fingerprint"] = fingerprint
    if text_duplicate and (meta.get("duplicate") or {}).get("status") != "file_duplicate":
        meta["duplicate"] = {
            "status": "text_duplicate",
            "matched_document_id": str(text_duplicate["id"]),
            "matched_document_name": text_duplicate["name"],
        }
        warnings = list(meta.get("warnings") or [])
        warnings.append(
            {
                "code": "text_duplicate",
                "message": "存在正文内容相同或高度一致的历史文档",
            }
        )
        meta["warnings"] = warnings
    else:
        meta.setdefault("duplicate", {"status": "none"})

    meta["ingest_task"] = {
        "status": "done",
        "raw_chars": cleaning_result.raw_chars,
        "cleaned_chars": cleaning_result.cleaned_chars,
        "raw_lines": cleaning_result.raw_lines,
        "cleaned_lines": cleaning_result.cleaned_lines,
        "removed_lines": cleaning_result.removed_lines,
        "removed_blank_lines": cleaning_result.removed_blank_lines,
        "removed_noise_lines": cleaning_result.removed_noise_lines,
        "cleaning_version": cleaning_result.cleaning_version,
        "text_fingerprint": fingerprint,
        "chunk_strategy": chunk_strategy,
        "chunk_method": chunk_method,
        "fallback_chunking": fallback_chunking,
        "chunk_count": chunk_count,
        "embedding_dim": embedding_dim,
        "block_count": block_count,
        "located_chunk_count": located_chunk_count,
        "page_located_chunk_count": page_located_chunk_count,
    }
    return meta


def resolve_chunking_config(kb_config: dict) -> dict:
    chunking = kb_config.get("chunking")
    if not isinstance(chunking, dict):
        chunking = {}
    return {
        "strategy": str(chunking.get("strategy") or kb_config.get("chunk_strategy") or "paragraph"),
        "chunk_size": chunking.get("chunk_size", kb_config.get("chunk_size", 800)),
        "overlap": chunking.get("overlap", kb_config.get("overlap", 80)),
    }


def build_chunk_ingest_meta(
    chunk_meta: dict | None,
    *,
    content_hash: str,
    cleaning_version: str,
    duplicate_in_document: bool,
    source_meta: dict | None = None,
) -> dict:
    meta = dict(chunk_meta or {})
    if source_meta:
        meta.update(source_meta)
    meta["content_hash"] = content_hash
    meta["cleaning_version"] = cleaning_version
    if duplicate_in_document:
        meta["duplicate_in_document"] = True
    return meta


def clean_located_blocks(
    blocks: list[object],
    cleaned_text: str,
    config: dict | None,
) -> list[TextBlock]:
    located: list[TextBlock] = []
    block_cleaning_config = dict(config or {})
    block_cleaning_config["remove_repeated_headers"] = False
    for index, block in enumerate(blocks, start=1):
        result = clean_text(str(getattr(block, "text", "") or ""), block_cleaning_config)
        text = result.text
        if not text:
            continue
        if cleaned_text and text not in cleaned_text:
            continue
        located.append(
            TextBlock(
                text=text,
                page=to_int_or_none(getattr(block, "page", None)),
                paragraph=to_int_or_none(getattr(block, "paragraph", None)),
                block_index=to_int_or_none(getattr(block, "block_index", None))
                or index,
            )
        )
    return located


def is_chunk_located(meta: dict) -> bool:
    return any(
        meta.get(key) is not None
        for key in (
            "page_start",
            "page_end",
            "paragraph_start",
            "paragraph_end",
            "block_start",
            "block_end",
        )
    )


def to_int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def document_source_meta(document: Document) -> dict:
    meta = document.meta or {}
    source = meta.get("source")
    defaults = {
        "source_name": document.name,
        "source_type": "upload",
        "tags": [],
        "version_label": "v1",
        "published_at": None,
    }
    if isinstance(source, dict):
        merged = {**defaults, **source}
    else:
        merged = defaults
    return {
        "source_name": merged.get("source_name") or document.name,
        "source_type": merged.get("source_type") or "upload",
        "tags": merged.get("tags") if isinstance(merged.get("tags"), list) else [],
        "version_label": merged.get("version_label"),
        "published_at": merged.get("published_at"),
    }


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
