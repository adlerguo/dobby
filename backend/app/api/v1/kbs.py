from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, get_current_auth, require_perm
from app.core.database import get_db
from app.rag.retrieve import retrieve_chunks
from app.rag.tasks import enqueue_parse_document
from app.repositories import DocumentRepository, KnowledgeBaseRepository
from app.schemas import DocumentOut, KnowledgeBaseCreate, KnowledgeBaseOut, KnowledgeBaseUpdate, RetrieveIn, RetrieveOut
from app.services import archive_kb, create_kb, delete_document, update_kb, upload_document
from app.services.audit_service import write_audit

router = APIRouter(tags=["knowledge_bases"])


def kb_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    if detail.endswith("_exists"):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    if detail.endswith("_not_found"):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


@router.get("/kbs", response_model=list[KnowledgeBaseOut], summary="List knowledge bases")
async def list_kbs(
    type: str | None = Query(default=None),
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> list:
    repo = KnowledgeBaseRepository(db, auth.tenant_id)
    return list(await repo.list_by_type(type))


@router.post(
    "/kbs",
    response_model=KnowledgeBaseOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create knowledge base",
)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    request: Request,
    auth: AuthContext = Depends(require_perm("kb:create")),
    db: AsyncSession = Depends(get_db),
):
    try:
        kb = await create_kb(db, tenant_id=auth.tenant_id, created_by=auth.user_id, payload=payload)
    except ValueError as exc:
        raise kb_error(exc) from exc
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="kb.create",
        resource_type="kb",
        resource_id=kb.id,
        detail={"name": kb.name, "type": kb.type},
        request=request,
    )
    return kb


@router.get("/kbs/{kb_id}", response_model=KnowledgeBaseOut, summary="Get knowledge base")
async def get_kb(
    kb_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
):
    repo = KnowledgeBaseRepository(db, auth.tenant_id)
    kb = await repo.get_by_id(kb_id)
    if kb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="kb_not_found")
    return kb


@router.patch("/kbs/{kb_id}", response_model=KnowledgeBaseOut, summary="Update knowledge base")
async def patch_kb(
    kb_id: UUID,
    payload: KnowledgeBaseUpdate,
    request: Request,
    auth: AuthContext = Depends(require_perm("kb:create")),
    db: AsyncSession = Depends(get_db),
):
    try:
        kb = await update_kb(db, tenant_id=auth.tenant_id, kb_id=kb_id, payload=payload)
    except ValueError as exc:
        raise kb_error(exc) from exc
    if kb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="kb_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="kb.update",
        resource_type="kb",
        resource_id=kb.id,
        detail={"fields": sorted(payload.model_dump(exclude_unset=True).keys())},
        request=request,
    )
    return kb


@router.delete("/kbs/{kb_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Archive knowledge base")
async def delete_kb(
    kb_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_perm("kb:create")),
    db: AsyncSession = Depends(get_db),
) -> None:
    deleted = await archive_kb(db, tenant_id=auth.tenant_id, kb_id=kb_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="kb_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="kb.archive",
        resource_type="kb",
        resource_id=kb_id,
        request=request,
    )


@router.post(
    "/kbs/{kb_id}/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload document",
)
async def upload_kb_document(
    kb_id: UUID,
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_perm("kb:create")),
    db: AsyncSession = Depends(get_db),
):
    try:
        document = await upload_document(db, tenant_id=auth.tenant_id, kb_id=kb_id, file=file)
    except ValueError as exc:
        raise kb_error(exc) from exc
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="kb_not_found")
    background_tasks.add_task(enqueue_parse_document, document.id)
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="document.upload",
        resource_type="document",
        resource_id=document.id,
        detail={"kb_id": str(kb_id), "name": document.name, "mime": document.mime, "size": document.size},
        request=request,
    )
    return document


@router.get("/kbs/{kb_id}/documents", response_model=list[DocumentOut], summary="List documents")
async def list_kb_documents(
    kb_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> list:
    kb_repo = KnowledgeBaseRepository(db, auth.tenant_id)
    if await kb_repo.get_by_id(kb_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="kb_not_found")
    repo = DocumentRepository(db, auth.tenant_id)
    return list(await repo.list_by_kb(kb_id))


@router.post("/kbs/{kb_id}/retrieve", response_model=RetrieveOut, summary="Retrieve chunks")
async def retrieve_kb_chunks(
    kb_id: UUID,
    payload: RetrieveIn,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> RetrieveOut:
    result = await retrieve_chunks(
        db,
        tenant_id=auth.tenant_id,
        kb_id=kb_id,
        query=payload.query,
        top_k=payload.top_k,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="kb_not_found")
    return result


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete document")
async def remove_document(
    document_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_perm("kb:create")),
    db: AsyncSession = Depends(get_db),
) -> None:
    deleted = await delete_document(db, tenant_id=auth.tenant_id, document_id=document_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="document.delete",
        resource_type="document",
        resource_id=document_id,
        request=request,
    )
