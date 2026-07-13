from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_perm
from app.core.database import get_db
from app.schemas import AuditLogOut
from app.services.audit_service import list_audit_logs

router = APIRouter(tags=["audit"])


@router.get("/audit-logs", response_model=list[AuditLogOut], summary="List audit logs")
async def list_audit_logs_api(
    user_id: UUID | None = Query(default=None),
    action: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(require_perm("audit:view")),
    db: AsyncSession = Depends(get_db),
) -> list:
    return await list_audit_logs(
        db,
        tenant_id=auth.tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
