from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: UUID
    tenant_id: UUID
    user_id: UUID | None
    action: str | None
    resource_type: str | None
    resource_id: UUID | None
    ip: str | None
    detail: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}
