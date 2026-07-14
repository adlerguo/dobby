from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, get_current_auth, require_perm
from app.core.database import get_db
from app.repositories import ToolRepository
from app.schemas import ToolCreate, ToolOut, ToolRunIn, ToolRunOut, ToolUpdate
from app.services import create_tool, disable_tool, run_tool, update_tool
from app.services.audit_service import write_audit

router = APIRouter(prefix="/tools", tags=["tools"])


def tool_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    if detail.endswith("_exists"):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    if detail.endswith("_not_found"):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


@router.get("", response_model=list[ToolOut], summary="List tools")
async def list_tools(
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> list:
    repo = ToolRepository(db, auth.tenant_id)
    return list(await repo.list())


@router.post("", response_model=ToolOut, status_code=status.HTTP_201_CREATED, summary="Create tool")
async def create_tool_api(
    payload: ToolCreate,
    request: Request,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
):
    try:
        tool = await create_tool(db, tenant_id=auth.tenant_id, payload=payload)
    except ValueError as exc:
        raise tool_error(exc) from exc
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="tool.create",
        resource_type="tool",
        resource_id=tool.id,
        detail={"name": tool.name, "type": tool.type},
        request=request,
    )
    return tool


@router.get("/{tool_id}", response_model=ToolOut, summary="Get tool")
async def get_tool(
    tool_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
):
    repo = ToolRepository(db, auth.tenant_id)
    tool = await repo.get_by_id(tool_id)
    if tool is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tool_not_found")
    return tool


@router.patch("/{tool_id}", response_model=ToolOut, summary="Update tool")
async def update_tool_api(
    tool_id: UUID,
    payload: ToolUpdate,
    request: Request,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
):
    try:
        tool = await update_tool(db, tenant_id=auth.tenant_id, tool_id=tool_id, payload=payload)
    except ValueError as exc:
        raise tool_error(exc) from exc
    if tool is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tool_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="tool.update",
        resource_type="tool",
        resource_id=tool.id,
        detail={"fields": sorted(payload.model_dump(exclude_unset=True).keys())},
        request=request,
    )
    return tool


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Disable tool")
async def delete_tool_api(
    tool_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
) -> None:
    deleted = await disable_tool(db, tenant_id=auth.tenant_id, tool_id=tool_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tool_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="tool.disable",
        resource_type="tool",
        resource_id=tool_id,
        request=request,
    )


@router.post("/{tool_id}/run", response_model=ToolRunOut, summary="Run tool")
async def run_tool_api(
    tool_id: UUID,
    payload: ToolRunIn,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> ToolRunOut:
    result = await run_tool(db, tenant_id=auth.tenant_id, tool_id=tool_id, input=payload.input)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tool_not_found")
    if result.output.get("error") == "forbidden":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=result.output)
    return result
