from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PublishedAppCreate(BaseModel):
    model_config = {"extra": "forbid"}

    agent_id: UUID
    name: str | None = Field(default=None, min_length=1)
    publish_type: str = Field(default="api", pattern=r"^api$")
    config: dict[str, Any] = Field(default_factory=dict)


class PublishedAppOut(BaseModel):
    id: UUID
    tenant_id: UUID
    agent_id: UUID
    name: str
    status: str
    publish_type: str
    config: dict[str, Any]
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AppApiKeyCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(default="默认 API Key", min_length=1)
    scopes: list[str] = Field(default_factory=lambda: ["agent:invoke"])
    expires_at: datetime | None = None


class AppApiKeyOut(BaseModel):
    id: UUID
    tenant_id: UUID
    app_id: UUID
    name: str
    key_prefix: str
    scopes: list[str]
    status: str
    expires_at: datetime | None
    created_by: UUID | None
    created_at: datetime
    last_used_at: datetime | None

    model_config = {"from_attributes": True}


class AppApiKeyCreatedOut(AppApiKeyOut):
    api_key: str


class AppApiKeyStatusIn(BaseModel):
    model_config = {"extra": "forbid"}

    status: str = Field(pattern=r"^(active|disabled)$")
