from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


FeedbackRating = Literal["positive", "negative"]
FeedbackReason = Literal[
    "accurate",
    "inaccurate",
    "no_evidence",
    "wrong_citation",
    "bad_format",
    "tool_failed",
    "unsafe",
    "other",
]


class FeedbackCreate(BaseModel):
    model_config = {"extra": "forbid"}

    rating: FeedbackRating
    reason: FeedbackReason | None = None
    comment: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class FeedbackOut(BaseModel):
    id: UUID
    tenant_id: UUID
    message_id: UUID
    conversation_id: UUID | None = None
    agent_id: UUID | None = None
    trace_id: UUID | None = None
    rating: str
    reason: str | None = None
    comment: str | None = None
    citations: list[dict[str, Any]]
    meta: dict[str, Any]
    created_by: UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
