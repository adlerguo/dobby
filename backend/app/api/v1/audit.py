import csv
import json
from collections.abc import AsyncGenerator
from datetime import datetime
from io import StringIO
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_perm
from app.core.database import get_db
from app.schemas import AuditLogOut
from app.services.audit_service import (
    AUDIT_LOG_EXPORT_LIMIT,
    is_audit_log_export_truncated,
    iter_export_audit_logs,
    list_audit_logs,
)

router = APIRouter(tags=["audit"])


@router.get("/audit-logs", response_model=list[AuditLogOut], summary="List audit logs")
async def list_audit_logs_api(
    user_id: UUID | None = Query(default=None),
    action: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
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
        date_from=date_from or start,
        date_to=date_to or end,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/audit-logs/export", response_model=list[AuditLogOut], summary="Export audit logs"
)
async def export_audit_logs_api(
    response: Response,
    user_id: UUID | None = Query(default=None),
    action: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    format: str = Query(default="csv", pattern="^(csv|json)$"),
    auth: AuthContext = Depends(require_perm("audit:view")),
    db: AsyncSession = Depends(get_db),
) -> list | StreamingResponse:
    filters = {
        "tenant_id": auth.tenant_id,
        "user_id": user_id,
        "action": action,
        "resource_type": resource_type,
        "date_from": date_from or start,
        "date_to": date_to or end,
    }
    truncated = await is_audit_log_export_truncated(
        db, **filters, limit=AUDIT_LOG_EXPORT_LIMIT
    )
    if format == "json":
        response.headers["X-Export-Truncated"] = "true" if truncated else "false"
        return [
            log
            async for log in iter_export_audit_logs(
                db, **filters, limit=AUDIT_LOG_EXPORT_LIMIT
            )
        ]

    filename = f"audit_logs_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"
    return StreamingResponse(
        audit_logs_csv_rows(db, filters),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "X-Export-Truncated": "true" if truncated else "false",
        },
    )


async def audit_logs_csv_rows(
    db: AsyncSession, filters: dict
) -> AsyncGenerator[str, None]:
    yield csv_row(
        [
            "created_at",
            "user_id",
            "action",
            "resource_type",
            "resource_id",
            "ip",
            "detail",
        ]
    )
    async for log in iter_export_audit_logs(
        db, **filters, limit=AUDIT_LOG_EXPORT_LIMIT
    ):
        yield csv_row(
            [
                log.created_at.isoformat() if log.created_at else "",
                str(log.user_id) if log.user_id else "",
                log.action or "",
                log.resource_type or "",
                str(log.resource_id) if log.resource_id else "",
                log.ip or "",
                json.dumps(log.detail or {}, ensure_ascii=False, default=str),
            ]
        )


def csv_row(values: list[str]) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(values)
    return output.getvalue()
