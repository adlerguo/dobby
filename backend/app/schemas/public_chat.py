from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.kb import CitationOut


class PublicChatIn(BaseModel):
    model_config = {"extra": "forbid"}

    query: str = Field(min_length=1)
    conversation_id: UUID | None = None
    stream: bool = False
    max_tokens: int = Field(default=3500, ge=256, le=32000)
    history_limit: int = Field(default=12, ge=0, le=50)
    top_k: int | None = Field(default=None, ge=1, le=20)
    score_threshold: float | None = Field(default=None, ge=0, le=1)
    match_type: str | None = Field(default=None, pattern=r"^(hybrid|vector|keyword)$")
    rerank_mode: Literal["off", "rule", "model"] | None = None


class PublicChatOut(BaseModel):
    answer: str
    citations: list[CitationOut]
    conversation_id: UUID
    usage: dict[str, Any]
