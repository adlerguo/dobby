from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class EvalCaseBase(BaseModel):
    target_type: str = "assistant"
    target_id: str
    scene: str | None = None
    query: str
    expected_answer: str | None = None
    expected_keywords: list[str] = Field(default_factory=list)
    scoring_config: dict = Field(default_factory=dict)


class EvalCaseCreate(EvalCaseBase):
    pass


class EvalCaseUpdate(BaseModel):
    target_type: str | None = None
    target_id: str | None = None
    scene: str | None = None
    query: str | None = None
    expected_answer: str | None = None
    expected_keywords: list[str] | None = None
    scoring_config: dict | None = None


class EvalCaseRead(EvalCaseBase):
    id: UUID
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EvalRunCreate(BaseModel):
    target_type: str = "assistant"
    target_id: str
    case_ids: list[UUID]
    concurrency: int = Field(default=2, ge=1, le=20)
    run_config: dict = Field(default_factory=dict)


class EvalRunItemRead(BaseModel):
    id: UUID
    run_id: UUID
    case_id: UUID | None
    status: str
    answer: str | None
    score: Decimal | None
    passed: bool | None
    failure_reason: str | None
    first_frame_latency_ms: int | None
    total_latency_ms: int | None
    frame_count: int | None
    conversation_id: str | None
    raw_response: dict
    retry_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EvalRunRead(BaseModel):
    id: UUID
    target_type: str
    target_id: str
    status: str
    total_cases: int
    completed_cases: int
    passed_cases: int
    failed_cases: int
    concurrency: int
    created_by: str
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    run_config: dict
    created_at: datetime
    updated_at: datetime
    items: list[EvalRunItemRead] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class EvalRunProgress(BaseModel):
    id: UUID
    status: str
    total_cases: int
    completed_cases: int
    passed_cases: int
    failed_cases: int
    error_message: str | None = None
