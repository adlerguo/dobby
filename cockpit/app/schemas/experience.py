from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ExperienceBase(BaseModel):
    target_type: str | None = None
    target_id: str | None = None
    scene: str | None = None
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)


class ExperienceCreate(ExperienceBase):
    pass


class ExperienceUpdate(BaseModel):
    target_type: str | None = None
    target_id: str | None = None
    scene: str | None = None
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    meta: dict | None = None


class ExperienceRead(ExperienceBase):
    id: UUID
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
