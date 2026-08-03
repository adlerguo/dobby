from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


IncidentStatus = Literal["open", "ignored", "resolved"]


class IncidentOut(BaseModel):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID | None = None
    message_id: UUID | None = None
    agent_id: UUID | None = None
    trace_id: UUID | None = None
    incident_type: str
    severity: str
    status: str
    title: str
    detail: dict[str, Any]
    resolution_note: str | None = None
    created_by: UUID | None = None
    resolved_by: UUID | None = None
    created_at: datetime
    resolved_at: datetime | None = None

    model_config = {"from_attributes": True}


class IncidentUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    status: IncidentStatus | None = None
    resolution_note: str | None = None


class IncidentCreate(BaseModel):
    model_config = {"extra": "forbid"}

    conversation_id: UUID | None = None
    message_id: UUID | None = None
    agent_id: UUID | None = None
    trace_id: UUID | None = None
    incident_type: str
    severity: Literal["low", "medium", "high"] = "medium"
    title: str = Field(min_length=1)
    detail: dict[str, Any] = Field(default_factory=dict)
