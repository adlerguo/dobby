from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

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
    type: str = Field(
        pattern=r"^(doc_regulation|policy|compliance|sop|standard|case|material|faq)$"
    )
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
    status: str | None = Field(
        default=None, pattern=r"^(active|disabled|draft|archived)$"
    )


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


class KnowledgeBaseHealthOut(BaseModel):
    kb_id: UUID
    document_total: int
    document_success: int
    document_failed: int
    document_processing: int
    chunk_total: int
    chunks_without_embedding: int
    avg_chunk_length: float
    short_chunk_ratio: float
    failure_reasons: dict[str, int]
    suggestions: list[str]


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
    logical_doc_id: UUID
    version_no: int
    version_status: str
    version_parent_id: UUID | None = None
    activated_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentSourceMeta(BaseModel):
    model_config = {"extra": "forbid"}

    source_name: str | None = None
    source_type: str | None = Field(
        default=None, pattern=r"^(upload|api|sync|manual)$"
    )
    tags: list[str] = Field(default_factory=list)
    version_label: str | None = None
    published_at: str | None = None
    author: str | None = None
    publisher: str | None = None
    effective_at: str | None = None
    expired_at: str | None = None

    @field_validator(
        "version_label",
        "published_at",
        "author",
        "publisher",
        "effective_at",
        "expired_at",
        mode="before",
    )
    @classmethod
    def trim_optional_string(cls, value):
        if value is None:
            return None
        value = str(value).strip()
        if value == "":
            return None
        return value

    @field_validator("source_name", mode="before")
    @classmethod
    def source_name_must_not_be_empty(cls, value):
        if value is None:
            return value
        value = str(value).strip()
        if not value:
            raise ValueError("source_name_required")
        return value

    @field_validator("tags", mode="before")
    @classmethod
    def clean_tags(cls, value):
        if value is None:
            return []
        seen: set[str] = set()
        tags: list[str] = []
        for item in value:
            tag = str(item).strip()
            if not tag or tag in seen:
                continue
            seen.add(tag)
            tags.append(tag)
            if len(tags) >= 20:
                break
        return tags

    @field_validator("published_at", "effective_at", "expired_at")
    @classmethod
    def validate_iso_date(cls, value):
        if value is None:
            return value
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("invalid_iso_date") from exc
        return value


class DocumentMetaUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    source: DocumentSourceMeta


class DocumentVersionOut(BaseModel):
    id: UUID
    logical_doc_id: UUID
    version_no: int
    version_status: str
    version_parent_id: UUID | None = None
    name: str
    parse_status: str | None
    meta: dict[str, Any]
    created_at: datetime
    activated_at: datetime | None = None

    model_config = {"from_attributes": True}


class DocumentVersionCreateOut(BaseModel):
    document: DocumentOut
    previous_active_id: UUID | None = None
    status: str
    warnings: list[str] = Field(default_factory=list)


class DocumentBatchItemOut(BaseModel):
    filename: str
    status: Literal["created", "failed"]
    document_id: UUID | None = None
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)


class DocumentBatchCreateOut(BaseModel):
    batch_id: UUID
    total: int
    created: int
    failed: int
    items: list[DocumentBatchItemOut]


class DocumentBatchStatusItemOut(BaseModel):
    document_id: UUID
    name: str
    parse_status: str | None
    error_code: str | None = None
    created_at: datetime


class DocumentBatchStatusOut(BaseModel):
    batch_id: UUID
    total: int
    document_success: int
    document_failed: int
    document_processing: int
    items: list[DocumentBatchStatusItemOut]


class DocumentChunkOut(BaseModel):
    id: UUID
    seq: int | None
    content: str
    content_length: int
    tokens: int | None
    meta: dict[str, Any]
    has_embedding: bool
    page_start: int | None = None
    page_end: int | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None
    block_start: int | None = None
    block_end: int | None = None
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
    rerank_mode: Literal["off", "rule", "model"] | None = None


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
    source_name: str | None = None
    source_type: str | None = None
    tags: list[str] = Field(default_factory=list)
    version_label: str | None = None
    published_at: str | None = None
    rerank_mode: str | None = None
    rerank_score: float | None = None
    rerank_factors: dict[str, Any] | None = None
    rerank_fallback: bool | None = None
    page_start: int | None = None
    page_end: int | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None
    block_start: int | None = None
    block_end: int | None = None


class CitationOut(BaseModel):
    chunk_id: UUID
    doc_id: UUID
    doc_name: str
    seq: int | None = None
    content_length: int
    score: float
    vector_score: float | None = None
    text_score: float | None = None
    match_channels: list[Literal["vector", "keyword"]]
    snippet: str
    source_name: str | None = None
    source_type: str | None = None
    tags: list[str] = Field(default_factory=list)
    version_label: str | None = None
    published_at: str | None = None
    rerank_mode: str | None = None
    rerank_score: float | None = None
    rerank_factors: dict[str, Any] | None = None
    rerank_fallback: bool | None = None
    page_start: int | None = None
    page_end: int | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None
    block_start: int | None = None
    block_end: int | None = None


class RetrieveOut(BaseModel):
    chunks: list[RetrievedChunkOut]
    citations: list[CitationOut]
    rerank_mode: str | None = None
    rerank_fallback: bool | None = None
    rerank_latency_ms: int | None = None
    rerank_input_count: int | None = None
    rerank_output_count: int | None = None
