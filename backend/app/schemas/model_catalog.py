from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class ModelCatalogOut(BaseModel):
    id: UUID
    provider: str
    model_code: str
    display_name: str
    model_type: str
    description: str | None
    context_window: int | None
    supports_streaming: bool
    supports_tools: bool
    supports_vision: bool
    default_base_url: str
    protocol: str
    recommended_parameters: dict[str, Any]
    official_url: str | None
    pricing: dict[str, Any]
    icon: str | None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
