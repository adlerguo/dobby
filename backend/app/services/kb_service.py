from io import BytesIO
from functools import partial
from uuid import UUID, uuid4

from anyio import to_thread
from fastapi import UploadFile
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import delete_object, upload_object
from app.models import Chunk, Document, KnowledgeBase
from app.repositories import DocumentRepository, KnowledgeBaseRepository
from app.schemas import KnowledgeBaseCreate, KnowledgeBaseUpdate
from app.services.validation import (
    detail_from_integrity_error,
    ensure_document_name_available,
    ensure_tenant_name_available,
)


async def create_kb(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    created_by: UUID,
    payload: KnowledgeBaseCreate,
) -> KnowledgeBase:
    repo = KnowledgeBaseRepository(db, tenant_id)
    await ensure_tenant_name_available(
        db,
        model=KnowledgeBase,
        tenant_id=tenant_id,
        name=payload.name,
        detail="kb_name_exists",
    )
    kb = KnowledgeBase(
        tenant_id=tenant_id,
        name=payload.name,
        type=payload.type,
        description=payload.description,
        config=payload.config,
        embedding_model=payload.embedding_model,
        status="active",
        created_by=created_by,
    )
    try:
        await repo.add(kb)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError(detail_from_integrity_error(exc, "kb_create_conflict")) from exc
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
        await ensure_tenant_name_available(
            db,
            model=KnowledgeBase,
            tenant_id=tenant_id,
            name=payload.name,
            detail="kb_name_exists",
            exclude_id=kb_id,
        )
    kb = await repo.update_by_id(kb_id, payload.model_dump(exclude_unset=True))
    if kb is None:
        return None
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError(detail_from_integrity_error(exc, "kb_update_conflict")) from exc
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
) -> Document | None:
    kb_repo = KnowledgeBaseRepository(db, tenant_id)
    kb = await kb_repo.get_by_id(kb_id)
    if kb is None or kb.status == "archived":
        return None

    content = await file.read()
    mime = file.content_type or "application/octet-stream"
    filename = file.filename or "uploaded_file"
    await ensure_document_name_available(db, tenant_id=tenant_id, kb_id=kb_id, name=filename)
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

    document = Document(
        id=document_id,
        tenant_id=tenant_id,
        kb_id=kb_id,
        name=filename,
        source_uri=source_uri,
        mime=mime,
        size=len(content),
        parse_status="pending",
        meta={"object_name": object_name},
    )
    repo = DocumentRepository(db, tenant_id)
    try:
        await repo.add(document)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError(detail_from_integrity_error(exc, "document_upload_conflict")) from exc
    await db.refresh(document)
    return document


async def delete_document(db: AsyncSession, *, tenant_id: UUID, document_id: UUID) -> bool:
    repo = DocumentRepository(db, tenant_id)
    document = await repo.get_by_id(document_id)
    if document is None:
        return False

    await db.execute(delete(Chunk).where(Chunk.doc_id == document.id, Chunk.tenant_id == tenant_id))
    await db.delete(document)
    await db.commit()
    await to_thread.run_sync(delete_object, document.source_uri)
    return True
