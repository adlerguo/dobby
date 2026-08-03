from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.agent_run import RuntimeToolCallIn


class ChatIn(BaseModel):
    model_config = {"extra": "forbid"}

    agent_id: UUID
    query: str = Field(min_length=1)
    conversation_id: UUID | None = None
    workspace_id: UUID | None = None
    max_tokens: int = Field(default=3500, ge=256, le=32000)
    history_limit: int = Field(default=12, ge=0, le=50)
    top_k: int | None = Field(default=None, ge=1, le=20)
    score_threshold: float | None = Field(default=None, ge=0, le=1)
    match_type: str | None = Field(default=None, pattern=r"^(hybrid|vector|keyword)$")
    rerank_mode: Literal["off", "rule", "model"] | None = None
    max_tool_rounds: int = Field(default=1, ge=0, le=3)
    tool_calls: list[RuntimeToolCallIn] = Field(default_factory=list)


class ConversationOut(BaseModel):
    id: UUID
    tenant_id: UUID
    user_id: UUID | None
    agent_id: UUID | None
    workspace_id: UUID | None
    title: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID | None
    role: str
    content: str | None
    tokens: int | None
    citations: list[dict[str, Any]]
    created_at: datetime

    model_config = {"from_attributes": True}
