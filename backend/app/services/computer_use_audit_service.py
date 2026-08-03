from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.audit_service import write_audit
from app.services.computer_use_sanitizer import sanitize_value


async def write_computer_use_audit(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    action: str,
    session_id: UUID | None = None,
    target_id: UUID | None = None,
    detail: dict[str, Any] | None = None,
    request: Request | None = None,
    commit: bool = True,
) -> None:
    payload = sanitize_value(
        {
            "session_id": str(session_id) if session_id else None,
            "target_id": str(target_id) if target_id else None,
            **(detail or {}),
        }
    )
    await write_audit(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type="computer_use",
        resource_id=session_id or target_id,
        detail=payload,
        request=request,
        commit=commit,
    )
