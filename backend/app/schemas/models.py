from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


MODEL_TYPES = "^(llm|embedding|rerank)$"


class ModelChannelCreate(BaseModel):
    model_config = {"extra": "forbid"}

    base_url: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    weight: int = Field(default=1, ge=1)
    rpm_limit: int | None = Field(default=None, ge=1)
    status: str = Field(default="active", pattern=r"^(active|disabled)$")


class ModelChannelOut(BaseModel):
    id: UUID
    tenant_id: UUID | None
    model_id: UUID | None
    base_url: str
    weight: int | None
    rpm_limit: int | None
    status: str | None
    health: str | None
    created_at: datetime | None

    model_config = {"from_attributes": True}


class ModelHubOut(BaseModel):
    id: UUID
    name: str
    provider: str | None
    type: str
    display_name: str | None
    description: str | None
    is_active: bool | None
    provider_config: dict[str, Any]
    import_source: str | None
    model_icon_path: str | None
    publish_date: str | None
    scope_type: str | None
    created_at: datetime | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class ModelHubCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1)
    provider: str | None = None
    type: str = Field(pattern=MODEL_TYPES)
    display_name: str | None = None
    description: str | None = None
    is_active: bool = True
    provider_config: dict[str, Any] = Field(default_factory=dict)
    import_source: str = "external"
    model_icon_path: str | None = None
    publish_date: str | None = None
    scope_type: str = "tenant"
    default_channel: ModelChannelCreate | None = None


class ModelHubUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str | None = Field(default=None, min_length=1)
    provider: str | None = None
    type: str | None = Field(default=None, pattern=MODEL_TYPES)
    display_name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    provider_config: dict[str, Any] | None = None
    import_source: str | None = None
    model_icon_path: str | None = None
    publish_date: str | None = None
    scope_type: str | None = None


class ModelStatusIn(BaseModel):
    model_config = {"extra": "forbid"}

    is_active: bool
