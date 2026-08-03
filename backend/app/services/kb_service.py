from datetime import datetime, timezone
from io import BytesIO
from functools import partial
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from anyio import to_thread
from fastapi import UploadFile
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ConflictError, DependencyError, ValidationError
from app.core.maas_auth import maas_service_headers
from app.core.storage import delete_object, upload_object
from app.models import Document, KnowledgeBase, Model, ModelChannel
from app.rag.chunk_store import delete_document_chunks
from app.rag.dedupe import file_sha256
from app.repositories import DocumentRepository, KnowledgeBaseRepository
from app.schemas import (
    DocumentBatchCreateOut,
    DocumentBatchItemOut,
    DocumentVersionCreateOut,
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
)
from app.services.validation import (
    detail_from_integrity_error,
    ensure_document_name_available,
    ensure_tenant_name_available,
)

ALLOWED_UPLOAD_TYPES = {
    ".txt": {"text/plain"},
    ".md": {"text/markdown", "text/plain"},
    ".pdf": {"application/pdf"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    },
}


async def create_kb(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    created_by: UUID,
    payload: KnowledgeBaseCreate,
) -> KnowledgeBase:
    repo = KnowledgeBaseRepository(db, tenant_id)
    try:
        await ensure_tenant_name_available(
            db,
            model=KnowledgeBase,
            tenant_id=tenant_id,
            name=payload.name,
            detail="kb_name_exists",
        )
    except ValueError as exc:
        raise ConflictError(code=str(exc)) from exc
    embedding_dim = await resolve_embedding_dim(
        db,
        tenant_id=tenant_id,
        embedding_model=payload.embedding_model,
    )
    kb = KnowledgeBase(
        tenant_id=tenant_id,
        name=payload.name,
        type=payload.type,
        description=payload.description,
        config=payload.config,
        embedding_model=payload.embedding_model,
        embedding_dim=embedding_dim,
        status="active",
        created_by=created_by,
    )
    try:
        await repo.add(kb)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            code=detail_from_integrity_error(exc, "kb_create_conflict")
        ) from exc
    await db.refresh(kb)
    return kb


async def update_kb(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    kb_id: UUID,
    payload: KnowledgeBaseUpdate,
) -> KnowledgeBase | None:
    repo = KnowledgeBaseRepository(db, tenant_id)
    if payload.name is not None:
        try:
            await ensure_tenant_name_available(
                db,
                model=KnowledgeBase,
                tenant_id=tenant_id,
                name=payload.name,
                detail="kb_name_exists",
                exclude_id=kb_id,
            )
        except ValueError as exc:
            raise ConflictError(code=str(exc)) from exc
    values = payload.model_dump(exclude_unset=True)
    if payload.embedding_model is not None:
        current_kb = await repo.get_by_id(kb_id)
        if current_kb is None:
            return None
        current_model = current_kb.embedding_model or "mock-embedding"
        if payload.embedding_model != current_model and await kb_has_documents(
            db, tenant_id=tenant_id, kb_id=kb_id
        ):
            raise ConflictError(code="kb_embedding_model_locked_has_documents")
        values["embedding_dim"] = await resolve_embedding_dim(
            db,
            tenant_id=tenant_id,
            embedding_model=payload.embedding_model,
        )
    kb = await repo.update_by_id(kb_id, values)
    if kb is None:
        return None
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            code=detail_from_integrity_error(exc, "kb_update_conflict")
        ) from exc
    await db.refresh(kb)
    return kb


async def archive_kb(db: AsyncSession, *, tenant_id: UUID, kb_id: UUID) -> bool:
    repo = KnowledgeBaseRepository(db, tenant_id)
    kb = await repo.update_by_id(kb_id, {"status": "archived"})
    if kb is None:
        return False
    await db.commit()
    return True


async def upload_document(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    kb_id: UUID,
    file: UploadFile,
    extra_meta: dict | None = None,
) -> Document | None:
    kb_repo = KnowledgeBaseRepository(db, tenant_id)
    kb = await kb_repo.get_by_id(kb_id)
    if kb is None or kb.status == "archived":
        return None

    filename = file.filename or "uploaded_file"
    try:
        await ensure_document_name_available(
            db, tenant_id=tenant_id, kb_id=kb_id, name=filename
        )
    except ValueError as exc:
        raise ConflictError(code=str(exc)) from exc
    document = await create_document_from_upload(
        db,
        tenant_id=tenant_id,
        kb_id=kb_id,
        file=file,
        extra_meta=extra_meta,
        logical_doc_id=None,
        version_no=1,
        version_status="active",
        version_parent_id=None,
    )
    repo = DocumentRepository(db, tenant_id)
    try:
        await repo.add(document)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            code=detail_from_integrity_error(exc, "document_upload_conflict")
        ) from exc
    await db.refresh(document)
    return document


async def create_document_from_upload(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    kb_id: UUID,
    file: UploadFile,
    extra_meta: dict | None,
    logical_doc_id: UUID | None,
    version_no: int,
    version_status: str,
    version_parent_id: UUID | None,
) -> Document:
    mime = file.content_type or "application/octet-stream"
    filename = file.filename or "uploaded_file"
    validate_upload_type(filename, mime)
    content = await file.read()
    content_sha256 = file_sha256(content)
    if len(content) > settings.upload_max_bytes:
        raise ValidationError(
            code="upload_file_too_large",
            detail={
                "max_bytes": settings.upload_max_bytes,
                "actual_bytes": len(content),
            },
        )
    duplicate = await find_duplicate_document_by_meta(
        db,
        tenant_id=tenant_id,
        kb_id=kb_id,
        key="file_sha256",
        value=content_sha256,
    )
    document_id = uuid4()
    object_name = f"tenants/{tenant_id}/kbs/{kb_id}/documents/{document_id}/{filename}"
    source_uri = await to_thread.run_sync(
        partial(
            upload_object,
            object_name=object_name,
            data=BytesIO(content),
            length=len(content),
            content_type=mime,
        )
    )

    meta = build_upload_meta(
        object_name=object_name,
        extra_meta=extra_meta,
        content_sha256=content_sha256,
        duplicate=duplicate,
        filename=filename,
    )
    meta.setdefault(
        "version",
        {
            "version_no": version_no,
            "parent_document_id": str(version_parent_id)
            if version_parent_id
            else None,
            "created_from": "upload",
        },
    )
    now = datetime.now(timezone.utc)
    return Document(
        id=document_id,
        tenant_id=tenant_id,
        kb_id=kb_id,
        name=filename,
        source_uri=source_uri,
        mime=mime,
        size=len(content),
        parse_status="pending",
        meta=meta,
        logical_doc_id=logical_doc_id or document_id,
        version_no=version_no,
        version_status=version_status,
        version_parent_id=version_parent_id,
        activated_at=now if version_status == "active" else None,
    )


async def upload_document_version(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    file: UploadFile,
    version_label: str | None = None,
    activate: bool = False,
) -> DocumentVersionCreateOut | None:
    repo = DocumentRepository(db, tenant_id)
    parent = await repo.get_by_id(document_id)
    if parent is None:
        return None

    logical_doc_id = parent.logical_doc_id or parent.id
    version_no = await next_document_version_no(
        db,
        tenant_id=tenant_id,
        kb_id=parent.kb_id,
        logical_doc_id=logical_doc_id,
    )
    source_meta = {
        "source_name": file.filename or parent.name,
        "source_type": "upload",
        "version_label": clean_version_label(version_label) or f"v{version_no}",
    }
    extra_meta = {
        "source": source_meta,
        "version": {
            "version_no": version_no,
            "parent_document_id": str(parent.id),
            "created_from": "upload",
        },
    }
    document = await create_document_from_upload(
        db,
        tenant_id=tenant_id,
        kb_id=parent.kb_id,
        file=file,
        extra_meta=extra_meta,
        logical_doc_id=logical_doc_id,
        version_no=version_no,
        version_status="inactive",
        version_parent_id=parent.id,
    )
    await repo.add(document)
    warnings: list[str] = []
    if activate:
        warnings.append("document_version_created_inactive_until_parsed")
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            code=detail_from_integrity_error(exc, "document_version_create_conflict")
        ) from exc
    await db.refresh(document)
    return DocumentVersionCreateOut(
        document=document,
        previous_active_id=None,
        status="inactive",
        warnings=warnings,
    )


async def list_document_versions(
    db: AsyncSession, *, tenant_id: UUID, document_id: UUID
) -> list[Document] | None:
    repo = DocumentRepository(db, tenant_id)
    document = await repo.get_by_id(document_id)
    if document is None:
        return None
    logical_doc_id = document.logical_doc_id or document.id
    result = await db.execute(
        select(Document)
        .where(
            Document.tenant_id == tenant_id,
            Document.kb_id == document.kb_id,
            Document.logical_doc_id == logical_doc_id,
        )
        .order_by(Document.version_no.desc(), Document.created_at.desc())
    )
    return list(result.scalars().all())


async def activate_document_version(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
) -> DocumentVersionCreateOut | None:
    repo = DocumentRepository(db, tenant_id)
    document = await repo.get_by_id(document_id)
    version = await repo.get_by_id(version_id)
    if document is None or version is None:
        return None
    if document.kb_id != version.kb_id or document.logical_doc_id != version.logical_doc_id:
        raise ValidationError(code="document_version_mismatch")
    if version.parse_status != "done":
        raise ValidationError(code="document_version_not_ready")
    previous_active_id = await active_document_id(
        db,
        tenant_id=tenant_id,
        kb_id=version.kb_id,
        logical_doc_id=version.logical_doc_id,
    )
    await deactivate_document_versions(
        db,
        tenant_id=tenant_id,
        kb_id=version.kb_id,
        logical_doc_id=version.logical_doc_id,
    )
    version.version_status = "active"
    version.activated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(version)
    return DocumentVersionCreateOut(
        document=version,
        previous_active_id=previous_active_id,
        status="active",
    )


async def next_document_version_no(
    db: AsyncSession, *, tenant_id: UUID, kb_id: UUID, logical_doc_id: UUID
) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(Document.version_no), 0)).where(
            Document.tenant_id == tenant_id,
            Document.kb_id == kb_id,
            Document.logical_doc_id == logical_doc_id,
        )
    )
    return int(result.scalar_one() or 0) + 1


async def active_document_id(
    db: AsyncSession, *, tenant_id: UUID, kb_id: UUID, logical_doc_id: UUID
) -> UUID | None:
    result = await db.execute(
        select(Document.id).where(
            Document.tenant_id == tenant_id,
            Document.kb_id == kb_id,
            Document.logical_doc_id == logical_doc_id,
            Document.version_status == "active",
        )
    )
    return result.scalar_one_or_none()


async def deactivate_document_versions(
    db: AsyncSession, *, tenant_id: UUID, kb_id: UUID, logical_doc_id: UUID
) -> None:
    await db.execute(
        update(Document)
        .where(
            Document.tenant_id == tenant_id,
            Document.kb_id == kb_id,
            Document.logical_doc_id == logical_doc_id,
            Document.version_status == "active",
        )
        .values(version_status="inactive")
    )


def clean_version_label(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


async def upload_documents_batch(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    kb_id: UUID,
    files: list[UploadFile],
) -> tuple[DocumentBatchCreateOut, list[Document]] | None:
    kb_repo = KnowledgeBaseRepository(db, tenant_id)
    kb = await kb_repo.get_by_id(kb_id)
    if kb is None or kb.status == "archived":
        return None

    batch_id = uuid4()
    items: list[DocumentBatchItemOut] = []
    created_documents: list[Document] = []
    for file in files:
        filename = file.filename or "uploaded_file"
        try:
            document = await upload_document(
                db,
                tenant_id=tenant_id,
                kb_id=kb_id,
                file=file,
                extra_meta={"batch_id": str(batch_id)},
            )
        except Exception as exc:
            items.append(
                DocumentBatchItemOut(
                    filename=filename,
                    status="failed",
                    error=batch_upload_error_code(exc),
                )
            )
            continue
        if document is None:
            items.append(
                DocumentBatchItemOut(
                    filename=filename,
                    status="failed",
                    error="kb_not_found",
                )
            )
            continue
        created_documents.append(document)
        items.append(
            DocumentBatchItemOut(
                filename=filename,
                status="created",
                document_id=document.id,
            )
        )

    created = len(created_documents)
    result = DocumentBatchCreateOut(
        batch_id=batch_id,
        total=len(files),
        created=created,
        failed=len(items) - created,
        items=items,
    )
    return result, created_documents


def batch_upload_error_code(exc: Exception) -> str:
    return getattr(exc, "code", None) or str(exc) or exc.__class__.__name__


async def find_duplicate_document_by_meta(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    kb_id: UUID,
    key: str,
    value: str,
    exclude_document_id: UUID | None = None,
) -> dict | None:
    if key not in {"file_sha256", "text_fingerprint"}:
        raise ValueError("unsupported_meta_duplicate_key")
    query = """
        SELECT id, name
        FROM documents
        WHERE tenant_id = :tenant_id
            AND kb_id = :kb_id
            AND meta ->> '{key}' = :value
    """.format(key=key)
    params = {
        "tenant_id": tenant_id,
        "kb_id": kb_id,
        "value": value,
    }
    if exclude_document_id is not None:
        query += " AND id != :exclude_document_id"
        params["exclude_document_id"] = exclude_document_id
    query += """
        ORDER BY created_at ASC
        LIMIT 1
        """
    result = await db.execute(text(query), params)
    row = result.mappings().first()
    return dict(row) if row else None


def build_upload_meta(
    *,
    object_name: str,
    extra_meta: dict | None,
    content_sha256: str,
    duplicate: dict | None,
    filename: str,
) -> dict:
    meta = {"object_name": object_name, **(extra_meta or {})}
    meta["source"] = build_default_source_meta(filename, meta.get("source"))
    meta["file_sha256"] = content_sha256
    if duplicate:
        meta["duplicate"] = {
            "status": "file_duplicate",
            "matched_document_id": str(duplicate["id"]),
            "matched_document_name": duplicate["name"],
        }
        warnings = list(meta.get("warnings") or [])
        warnings.append(
            {
                "code": "file_duplicate",
                "message": "存在内容完全相同的历史文档",
            }
        )
        meta["warnings"] = warnings
    else:
        meta.setdefault("duplicate", {"status": "none"})
    return meta


def build_default_source_meta(filename: str, source: object | None = None) -> dict:
    defaults = {
        "source_name": filename,
        "source_type": "upload",
        "tags": [],
        "version_label": "v1",
        "published_at": None,
    }
    if isinstance(source, dict):
        merged = {**defaults, **source}
        if not merged.get("source_name"):
            merged["source_name"] = filename
        if not merged.get("source_type"):
            merged["source_type"] = "upload"
        if not isinstance(merged.get("tags"), list):
            merged["tags"] = []
        return merged
    return defaults


async def delete_document(
    db: AsyncSession, *, tenant_id: UUID, document_id: UUID
) -> bool:
    repo = DocumentRepository(db, tenant_id)
    document = await repo.get_by_id(document_id)
    if document is None:
        return False

    await delete_document_chunks(db, tenant_id=tenant_id, document_id=document.id)
    await db.delete(document)
    await db.commit()
    await to_thread.run_sync(delete_object, document.source_uri)
    return True


def validate_upload_type(filename: str, mime: str) -> None:
    suffix = Path(filename).suffix.lower()
    allowed_mimes = ALLOWED_UPLOAD_TYPES.get(suffix)
    normalized_mime = (mime or "").split(";", 1)[0].strip().lower()
    if allowed_mimes is None:
        raise ValidationError(code="unsupported_document_type")
    if normalized_mime not in allowed_mimes:
        raise ValidationError(
            code="unsupported_document_type",
            detail={"filename": filename, "mime": normalized_mime},
        )


async def kb_has_documents(db: AsyncSession, *, tenant_id: UUID, kb_id: UUID) -> bool:
    result = await db.execute(
        select(Document.id)
        .where(
            Document.tenant_id == tenant_id,
            Document.kb_id == kb_id,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def resolve_embedding_dim(
    db: AsyncSession, *, tenant_id: UUID, embedding_model: str
) -> int:
    result = await db.execute(
        select(ModelChannel.id)
        .join(Model, Model.id == ModelChannel.model_id)
        .where(
            Model.name == embedding_model,
            Model.type == "embedding",
            ModelChannel.status == "active",
            ModelChannel.health != "failed",
            (ModelChannel.tenant_id == tenant_id) | (ModelChannel.tenant_id.is_(None)),
        )
        .order_by(ModelChannel.weight.desc(), ModelChannel.created_at.asc())
        .limit(1)
    )
    channel_id = result.scalar_one_or_none()
    if channel_id is None:
        raise ConflictError(code="no_active_model_channel")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{settings.maas_base_url.rstrip('/')}/admin/channels/{channel_id}/health",
                headers=maas_service_headers(),
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise DependencyError(code="maas_probe_failed") from exc

    if payload.get("health") != "ok":
        raise DependencyError(code=payload.get("error") or "embedding_probe_failed")
    embedding_dim = payload.get("embedding_dim")
    if embedding_dim is None:
        raise ValidationError(code="embedding_dim_unknown")
    if int(embedding_dim) not in {1024, 1536, 3072}:
        raise ValidationError(
            code="unsupported_embedding_dim",
            detail={"embedding_dim": int(embedding_dim)},
        )
    return int(embedding_dim)
