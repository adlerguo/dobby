from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ChannelCreate(BaseModel):
    model: str = Field(min_length=1)
    model_type: str = Field(default="llm", pattern=r"^(llm|embedding|rerank)$")
    provider: str | None = None
    tenant_id: UUID | None = None
    base_url: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    weight: int = Field(default=1, ge=1)
    rpm_limit: int | None = Field(default=None, ge=1)
    status: str = Field(default="active", pattern=r"^(active|disabled)$")


class ChannelUpdate(BaseModel):
    base_url: str | None = Field(default=None, min_length=1)
    api_key: str | None = Field(default=None, min_length=1)
    weight: int | None = Field(default=None, ge=1)
    rpm_limit: int | None = Field(default=None, ge=1)
    status: str | None = Field(default=None, pattern=r"^(active|disabled)$")
    health: str | None = Field(default=None, pattern=r"^(unknown|ok|failed)$")


class ChannelOut(BaseModel):
    id: UUID
    tenant_id: UUID | None
    model_id: UUID | None
    model: str | None
    model_type: str | None
    provider: str | None
    base_url: str
    weight: int | None
    rpm_limit: int | None
    status: str | None
    health: str | None
    error: str | None = None


class ChannelProbeIn(BaseModel):
    model: str = Field(min_length=1)
    model_type: str = Field(default="llm", pattern=r"^(llm|embedding|rerank)$")
    provider: str | None = None
    base_url: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    protocol: str = Field(default="openai_compatible")
    request_defaults: dict[str, Any] = Field(default_factory=dict)


class ChannelProbeOut(BaseModel):
    ok: bool
    health: str = Field(pattern=r"^(ok|failed)$")
    error: str | None = None


class ModelOut(BaseModel):
    id: UUID
    name: str
    provider: str | None
    type: str


class ChatMessage(BaseModel):
    role: str
    content: str | None = None


class ChatCompletionIn(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    stream_options: dict[str, Any] | None = None


class EmbeddingIn(BaseModel):
    model: str
    input: str | list[str]
    dimensions: int | None = Field(default=None, ge=1)


JsonDict = dict[str, Any]
