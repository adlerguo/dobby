from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EvalCaseCreate(BaseModel):
    model_config = {"extra": "forbid"}

    scene: str = Field(min_length=1)
    input: str = Field(min_length=1)
    expected: str | None = None
    assert_type: str = Field(
        default="contains",
        pattern=r"^(contains|not_contains|exact|citation_required|tool_success|latency_ms|always_pass)$",
    )
    threshold: float | None = None


class EvalCaseUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    scene: str | None = Field(default=None, min_length=1)
    input: str | None = Field(default=None, min_length=1)
    expected: str | None = None
    assert_type: str | None = Field(
        default=None,
        pattern=r"^(contains|not_contains|exact|citation_required|tool_success|latency_ms|always_pass)$",
    )
    threshold: float | None = None


class EvalCaseOut(BaseModel):
    id: UUID
    tenant_id: UUID
    scene: str | None
    input: str | None
    expected: str | None
    assert_type: str | None
    threshold: float | None

    model_config = {"from_attributes": True}


class EvalRunRequest(BaseModel):
    model_config = {"extra": "forbid"}

    case_ids: list[UUID] = Field(default_factory=list)
    workspace_id: UUID | None = None
    max_tokens: int = Field(default=3500, ge=256, le=32000)
    history_limit: int = Field(default=0, ge=0, le=50)
    top_k: int = Field(default=4, ge=1, le=20)
    max_tool_rounds: int = Field(default=1, ge=0, le=3)
    write_passed_experiences: bool = True


class EvalRunOut(BaseModel):
    id: UUID
    tenant_id: UUID
    agent_id: UUID | None
    case_id: UUID | None
    score: float | None
    passed: bool | None
    detail: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class EvalReportOut(BaseModel):
    agent_id: UUID
    total: int
    passed: int
    failed: int
    pass_rate: float
    runs: list[EvalRunOut]


class ExperienceCreate(BaseModel):
    model_config = {"extra": "forbid"}

    scene: str = Field(min_length=1)
    content: str = Field(min_length=1)
    meta: dict[str, Any] = Field(default_factory=dict)


class ExperienceOut(BaseModel):
    id: UUID
    tenant_id: UUID
    agent_id: UUID | None
    scene: str | None
    content: str | None
    meta: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}
