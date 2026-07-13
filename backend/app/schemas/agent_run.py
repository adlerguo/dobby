from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.context import ContextBuildOut
from app.schemas.kb import CitationOut


class RuntimeToolCallIn(BaseModel):
    model_config = {"extra": "forbid"}

    tool_id: UUID | None = None
    tool_name: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)


class AgentRunIn(BaseModel):
    model_config = {"extra": "forbid"}

    query: str = Field(min_length=1)
    conversation_id: UUID | None = None
    workspace_id: UUID | None = None
    max_tokens: int = Field(default=3500, ge=256, le=32000)
    history_limit: int = Field(default=12, ge=0, le=50)
    top_k: int | None = Field(default=None, ge=1, le=20)
    score_threshold: float | None = Field(default=None, ge=0, le=1)
    match_type: str | None = Field(default=None, pattern=r"^(hybrid|vector|keyword)$")
    max_tool_rounds: int = Field(default=1, ge=0, le=3)
    tool_calls: list[RuntimeToolCallIn] = Field(default_factory=list)


class RuntimeToolCallOut(BaseModel):
    tool_id: UUID
    tool_name: str
    input: dict[str, Any]
    output: dict[str, Any]
    status: str


class AgentRunOut(BaseModel):
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    trace_id: UUID
    answer: str
    citations: list[CitationOut]
    tool_results: list[RuntimeToolCallOut]
    usage: dict[str, Any]
    context: ContextBuildOut
