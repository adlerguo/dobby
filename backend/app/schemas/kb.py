from datetime import datetime
from typing import Any, Literal
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
    embedding_dim: int
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


class DocumentChunkOut(BaseModel):
    id: UUID
    seq: int | None
    content: str
    content_length: int
    tokens: int | None
    meta: dict[str, Any]
    has_embedding: bool
    created_at: datetime


class ReindexOut(BaseModel):
    kb_id: UUID
    document_count: int
    status: str


class RetrieveIn(BaseModel):
    model_config = {"extra": "forbid"}

    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    match_type: Literal["hybrid", "vector", "keyword"] = "hybrid"
    # Applies only to vector_score (cosine similarity, 0-1 range). Keyword-only
    # candidates have no vector_score and are not filtered by this threshold.
    score_threshold: float | None = Field(default=None, ge=0, le=1)


class RetrievedChunkOut(BaseModel):
    id: UUID
    doc_id: UUID
    doc_name: str
    seq: int | None = None
    content: str
    content_length: int
    score: float
    vector_score: float | None = None
    text_score: float | None = None
    match_channels: list[Literal["vector", "keyword"]]
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
