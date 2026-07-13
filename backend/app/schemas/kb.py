from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

KB_TYPES = {
    "doc_regulation",
    "policy",
    "compliance",
    "sop",
    "standard",
    "case",
    "material",
    "faq",
}


class KnowledgeBaseCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1)
    type: str = Field(pattern=r"^(doc_regulation|policy|compliance|sop|standard|case|material|faq)$")
    description: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    embedding_model: str = "mock-embedding"


class KnowledgeBaseUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str | None = Field(default=None, min_length=1)
    type: str | None = Field(
        default=None,
        pattern=r"^(doc_regulation|policy|compliance|sop|standard|case|material|faq)$",
    )
    description: str | None = None
    config: dict[str, Any] | None = None
    embedding_model: str | None = None
    status: str | None = Field(default=None, pattern=r"^(active|disabled|draft|archived)$")


class KnowledgeBaseOut(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    type: str
    description: str | None
    config: dict[str, Any]
    embedding_model: str | None
    status: str | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentOut(BaseModel):
    id: UUID
    tenant_id: UUID
    kb_id: UUID
    name: str
    source_uri: str | None
    mime: str | None
    size: int | None
    parse_status: str | None
    meta: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class RetrieveIn(BaseModel):
    model_config = {"extra": "forbid"}

    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class RetrievedChunkOut(BaseModel):
    id: UUID
    doc_id: UUID
    content: str
    score: float
    vector_score: float | None = None
    text_score: float | None = None
    meta: dict[str, Any]


class CitationOut(BaseModel):
    chunk_id: UUID
    doc_id: UUID
    doc_name: str
    score: float
    snippet: str


class RetrieveOut(BaseModel):
    chunks: list[RetrievedChunkOut]
    citations: list[CitationOut]
