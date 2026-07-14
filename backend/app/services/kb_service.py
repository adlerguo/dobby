from io import BytesIO
from functools import partial
from uuid import UUID, uuid4

import httpx
from anyio import to_thread
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.maas_auth import maas_service_headers
from app.core.storage import delete_object, upload_object
from app.models import Document, KnowledgeBase, Model, ModelChannel
from app.rag.chunk_store import delete_document_chunks
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
    values = payload.model_dump(exclude_unset=True)
    if payload.embedding_model is not None:
        current_kb = await repo.get_by_id(kb_id)
        if current_kb is None:
            return None
        current_model = current_kb.embedding_model or "mock-embedding"
        if payload.embedding_model != current_model and await kb_has_documents(db, tenant_id=tenant_id, kb_id=kb_id):
            raise ValueError("kb_embedding_model_locked_has_documents")
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

    await delete_document_chunks(db, tenant_id=tenant_id, document_id=document.id)
    await db.delete(document)
    await db.commit()
    await to_thread.run_sync(delete_object, document.source_uri)
    return True


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


async def resolve_embedding_dim(db: AsyncSession, *, tenant_id: UUID, embedding_model: str) -> int:
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
        raise ValueError("no_active_model_channel")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{settings.maas_base_url.rstrip('/')}/admin/channels/{channel_id}/health",
                headers=maas_service_headers(),
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise ValueError("maas_probe_failed") from exc

    if payload.get("health") != "ok":
        raise ValueError(payload.get("error") or "embedding_probe_failed")
    embedding_dim = payload.get("embedding_dim")
    if embedding_dim is None:
        raise ValueError("embedding_dim_unknown")
    if int(embedding_dim) not in {1024, 1536, 3072}:
        raise ValueError(f"unsupported_embedding_dim:{embedding_dim}")
    return int(embedding_dim)
