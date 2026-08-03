from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, get_current_auth, require_perm
from app.core.config import settings
from app.core.database import get_db
from app.schemas.computer_use import (
    ComputerUseCaptureIn,
    ComputerUseCaptureOut,
    ComputerUseConsentIn,
    ComputerUseSessionOut,
    ComputerUseStatusOut,
    ComputerUseTargetCreate,
    ComputerUseTargetOut,
)
from app.services.computer_use_audit_service import write_computer_use_audit
from app.services.computer_use_session_service import (
    capture_session_state,
    create_read_only_session,
    create_target,
    get_session,
    list_targets,
    stop_session,
)

router = APIRouter(tags=["computer-use"])


@router.get("/computer-use/status", response_model=ComputerUseStatusOut)
async def get_computer_use_status(
    auth: AuthContext = Depends(get_current_auth),
) -> ComputerUseStatusOut:
    enabled = bool(settings.computer_use_enabled)
    return ComputerUseStatusOut(
        enabled=enabled,
        reason=None if enabled else "computer_use_disabled",
        max_session_minutes=settings.computer_use_max_session_minutes,
        max_actions=settings.computer_use_max_actions,
    )


@router.get("/computer-use/targets", response_model=list[ComputerUseTargetOut])
async def list_computer_use_targets(
    workspace_id: UUID | None = None,
    enabled_only: bool = True,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> list[ComputerUseTargetOut]:
    rows = await list_targets(db, tenant_id=auth.tenant_id, workspace_id=workspace_id, enabled_only=enabled_only)
    return [ComputerUseTargetOut.model_validate(row) for row in rows]


@router.post("/computer-use/targets", response_model=ComputerUseTargetOut, status_code=201)
async def create_computer_use_target(
    payload: ComputerUseTargetCreate,
    auth: AuthContext = Depends(require_perm("audit:view")),
    db: AsyncSession = Depends(get_db),
) -> ComputerUseTargetOut:
    target = await create_target(db, tenant_id=auth.tenant_id, user_id=auth.user_id, payload=payload)
    return ComputerUseTargetOut.model_validate(target)


@router.post("/computer-use/sessions", response_model=ComputerUseSessionOut, status_code=201)
async def create_computer_use_session(
    payload: ComputerUseConsentIn,
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> ComputerUseSessionOut:
    try:
        session = await create_read_only_session(db, tenant_id=auth.tenant_id, user_id=auth.user_id, payload=payload)
        return ComputerUseSessionOut.model_validate(session)
    except Exception as exc:
        await write_computer_use_audit(
            db,
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            action="computer_use.session_rejected",
            target_id=payload.target_id,
            detail={
                "start_url": payload.start_url,
                "error_code": getattr(exc, "code", exc.__class__.__name__),
                "error_message": getattr(exc, "message", str(exc)),
            },
            request=request,
        )
        raise


@router.get("/computer-use/sessions/{session_id}", response_model=ComputerUseSessionOut)
async def get_computer_use_session(
    session_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> ComputerUseSessionOut:
    session = await get_session(db, tenant_id=auth.tenant_id, user_id=auth.user_id, session_id=session_id)
    return ComputerUseSessionOut.model_validate(session)


@router.post("/computer-use/sessions/{session_id}/capture", response_model=ComputerUseCaptureOut)
async def capture_computer_use_session(
    session_id: UUID,
    payload: ComputerUseCaptureIn,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> ComputerUseCaptureOut:
    return await capture_session_state(db, tenant_id=auth.tenant_id, user_id=auth.user_id, session_id=session_id, payload=payload)


@router.post("/computer-use/sessions/{session_id}/stop", response_model=ComputerUseSessionOut)
async def stop_computer_use_session(
    session_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> ComputerUseSessionOut:
    session = await stop_session(db, tenant_id=auth.tenant_id, user_id=auth.user_id, session_id=session_id)
    return ComputerUseSessionOut.model_validate(session)
