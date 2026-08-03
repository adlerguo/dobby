from typing import Any
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field

from app.schemas.kb import CitationOut, RetrievedChunkOut


class ContextBuildIn(BaseModel):
    model_config = {"extra": "forbid"}

    query: str = Field(min_length=1)
    conversation_id: UUID | None = None
    workspace_id: UUID | None = None
    max_tokens: int = Field(default=3500, ge=256, le=32000)
    history_limit: int = Field(default=12, ge=0, le=50)
    top_k: int | None = Field(default=None, ge=1, le=20)
    score_threshold: float | None = Field(default=None, ge=0, le=1)
    match_type: str | None = Field(default=None, pattern=r"^(hybrid|vector|keyword)$")


class ContextMessageOut(BaseModel):
    role: str
    content: str
    tokens: int


class ContextToolOut(BaseModel):
    model_config = {"populate_by_name": True}

    id: UUID
    name: str
    type: str
    tool_schema: dict[str, Any] = Field(
        validation_alias=AliasChoices("schema", "tool_schema"),
        serialization_alias="schema",
    )


class ContextBuildOut(BaseModel):
    agent_id: UUID
    conversation_id: UUID | None
    workspace_id: UUID | None
    messages: list[ContextMessageOut]
    tools: list[ContextToolOut]
    retrieved_chunks: list[RetrievedChunkOut]
    citations: list[CitationOut]
    token_budget: dict[str, int]
    truncation: dict[str, Any]
    intent: dict[str, Any] | None = None
    compression_strategy: str | None = None
    compression_applied: bool = False
    original_history_tokens: int | None = None
    compressed_history_tokens: int | None = None
    compressed_message_count: int = 0
    compression_fallback: bool = False
    compression_summary: str | None = None
