from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_perm
from app.core.database import get_db
from app.schemas import WorkspaceCreate, WorkspaceOut, WorkspaceResourceIn, WorkspaceUpdate
from app.services import (
    attach_workspace_resource,
    create_workspace,
    detach_workspace_resource,
    get_workspace,
    list_workspaces,
    update_workspace,
)
from app.services.audit_service import write_audit

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def workspace_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    if detail.endswith("_exists"):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    if detail.endswith("_not_found"):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


@router.get("", response_model=list[WorkspaceOut], summary="List workspaces")
async def list_workspace_api(
    auth: AuthContext = Depends(require_perm("dashboard:view")),
    db: AsyncSession = Depends(get_db),
) -> list[WorkspaceOut]:
    return await list_workspaces(db, tenant_id=auth.tenant_id)


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED, summary="Create workspace")
async def create_workspace_api(
    payload: WorkspaceCreate,
    request: Request,
    auth: AuthContext = Depends(require_perm("dashboard:view")),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceOut:
    try:
        workspace = await create_workspace(db, tenant_id=auth.tenant_id, user_id=auth.user_id, payload=payload)
    except ValueError as exc:
        raise workspace_error(exc) from exc
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="workspace.create",
        resource_type="workspace",
        resource_id=workspace.id,
        detail={"name": workspace.name},
        request=request,
    )
    return workspace


@router.get("/{workspace_id}", response_model=WorkspaceOut, summary="Get workspace")
async def get_workspace_api(
    workspace_id: UUID,
    auth: AuthContext = Depends(require_perm("dashboard:view")),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceOut:
    workspace = await get_workspace(db, tenant_id=auth.tenant_id, workspace_id=workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workspace_not_found")
    return workspace


@router.patch("/{workspace_id}", response_model=WorkspaceOut, summary="Update workspace")
async def update_workspace_api(
    workspace_id: UUID,
    payload: WorkspaceUpdate,
    request: Request,
    auth: AuthContext = Depends(require_perm("dashboard:view")),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceOut:
    try:
        workspace = await update_workspace(db, tenant_id=auth.tenant_id, workspace_id=workspace_id, payload=payload)
    except ValueError as exc:
        raise workspace_error(exc) from exc
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workspace_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="workspace.update",
        resource_type="workspace",
        resource_id=workspace.id,
        detail={"fields": sorted(payload.model_dump(exclude_unset=True).keys())},
        request=request,
    )
    return workspace


@router.post("/{workspace_id}/resources", response_model=WorkspaceOut, summary="Attach workspace resource")
async def attach_workspace_resource_api(
    workspace_id: UUID,
    payload: WorkspaceResourceIn,
    request: Request,
    auth: AuthContext = Depends(require_perm("dashboard:view")),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceOut:
    try:
        workspace = await attach_workspace_resource(
            db,
            tenant_id=auth.tenant_id,
            workspace_id=workspace_id,
            payload=payload,
        )
    except ValueError as exc:
        raise workspace_error(exc) from exc
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workspace_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="workspace.attach_resource",
        resource_type="workspace",
        resource_id=workspace.id,
        detail={"resource_type": payload.resource_type, "resource_id": str(payload.resource_id)},
        request=request,
    )
    return workspace


@router.delete("/{workspace_id}/resources", status_code=status.HTTP_204_NO_CONTENT, summary="Detach workspace resource")
async def detach_workspace_resource_api(
    workspace_id: UUID,
    payload: WorkspaceResourceIn,
    request: Request,
    auth: AuthContext = Depends(require_perm("dashboard:view")),
    db: AsyncSession = Depends(get_db),
) -> None:
    detached = await detach_workspace_resource(
        db,
        tenant_id=auth.tenant_id,
        workspace_id=workspace_id,
        payload=payload,
    )
    if not detached:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workspace_resource_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="workspace.detach_resource",
        resource_type="workspace",
        resource_id=workspace_id,
        detail={"resource_type": payload.resource_type, "resource_id": str(payload.resource_id)},
        request=request,
    )
