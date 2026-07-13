from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.models import ModelChannelOut, ModelHubOut


class ModelCenterConnectIn(BaseModel):
    model_config = {"extra": "forbid"}

    runtime_name: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    base_url: str | None = Field(default=None, min_length=1)
    weight: int = Field(default=1, ge=1)
    test_after_create: bool = True


class ConnectionTestOut(BaseModel):
    ok: bool
    health: str
    error: str | None = None


class ModelCenterConnectOut(BaseModel):
    model: ModelHubOut
    channel: ModelChannelOut
    test_result: ConnectionTestOut


class ModelCenterChannelTestOut(BaseModel):
    channel: ModelChannelOut
    test_result: ConnectionTestOut


class MaasChannelOut(BaseModel):
    id: UUID
    tenant_id: UUID | None
    model_id: UUID | None
    model: str | None = None
    model_type: str | None = None
    provider: str | None = None
    base_url: str
    weight: int | None = None
    rpm_limit: int | None = None
    status: str | None = None
    health: str | None = None
    error: str | None = None


class MaasProbeOut(BaseModel):
    ok: bool
    health: str
    error: str | None = None


class CatalogConnectionMeta(BaseModel):
    catalog_id: UUID
    catalog_code: str
    protocol: str
    availability: str | None = None
    default_base_url: str
    connected_at: datetime | None = None
    recommended_parameters: dict[str, Any] = Field(default_factory=dict)
