from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


RESOURCE_TYPES = {"kb", "agent", "tool", "model"}


class WorkspaceCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1)
    layout: dict[str, Any] = Field(default_factory=dict)


class WorkspaceUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str | None = Field(default=None, min_length=1)
    layout: dict[str, Any] | None = None


class WorkspaceResourceIn(BaseModel):
    model_config = {"extra": "forbid"}

    resource_type: str = Field(pattern=r"^(kb|agent|tool|model)$")
    resource_id: UUID


class WorkspaceResourceOut(BaseModel):
    id: UUID
    workspace_id: UUID | None
    resource_type: str | None
    resource_id: UUID | None
    resource_name: str | None = None
    resource_status: str | None = None

    model_config = {"from_attributes": True}


class WorkspaceOut(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    layout: dict[str, Any]
    created_by: UUID | None
    created_at: datetime
    resources: list[WorkspaceResourceOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}
