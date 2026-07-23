from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog

AUDIT_LOG_EXPORT_LIMIT = 50_000


async def write_audit(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    action: str,
    resource_type: str,
    resource_id: UUID | None = None,
    detail: dict[str, Any] | None = None,
    request: Request | None = None,
    commit: bool = True,
) -> AuditLog:
    audit = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip=client_ip(request),
        detail=detail or {},
    )
    db.add(audit)
    await db.flush()
    if commit:
        await db.commit()
        await db.refresh(audit)
    return audit


async def list_audit_logs(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditLog]:
    stmt = build_audit_log_query(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        date_from=date_from,
        date_to=date_to,
    )
    result = await db.execute(stmt.offset(offset).limit(limit))
    return list(result.scalars().all())


def build_audit_log_query(
    *,
    tenant_id: UUID,
    user_id: UUID | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> Select[tuple[AuditLog]]:
    stmt = select(AuditLog).where(AuditLog.tenant_id == tenant_id)
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if resource_type is not None:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if date_from is not None:
        stmt = stmt.where(AuditLog.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(AuditLog.created_at <= date_to)

    return stmt.order_by(AuditLog.created_at.desc())


async def iter_export_audit_logs(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = AUDIT_LOG_EXPORT_LIMIT,
):
    stmt = build_audit_log_query(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        date_from=date_from,
        date_to=date_to,
    ).limit(limit + 1)
    stream = await db.stream_scalars(stmt)
    count = 0
    try:
        async for audit_log in stream:
            if count >= limit:
                break
            count += 1
            yield audit_log
    finally:
        await stream.close()


async def is_audit_log_export_truncated(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = AUDIT_LOG_EXPORT_LIMIT,
) -> bool:
    stmt = (
        build_audit_log_query(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            date_from=date_from,
            date_to=date_to,
        )
        .offset(limit)
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


def client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host
