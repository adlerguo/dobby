from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

TaskStatus = Literal[
    "draft",
    "planned",
    "waiting_confirmation",
    "queued",
    "running",
    "waiting_external",
    "paused",
    "retrying",
    "succeeded",
    "partially_succeeded",
    "failed",
    "cancelled",
]

StepStatus = Literal[
    "pending",
    "waiting_dependency",
    "waiting_confirmation",
    "queued",
    "running",
    "waiting_external",
    "paused",
    "succeeded",
    "failed",
    "skipped",
    "cancelled",
]


class CopilotTaskWaitCondition(BaseModel):
    type: str
    resourceType: str
    resourceIdFromStep: str | None = None
    expectedStatuses: list[str] = Field(default_factory=list)
    failureStatuses: list[str] = Field(default_factory=list)
    timeoutSeconds: int = Field(default=3600, ge=30, le=86400)


class CopilotTaskPlanStep(BaseModel):
    clientStepId: str
    order: int = Field(ge=1)
    title: str = Field(min_length=1)
    description: str = ""
    toolName: str = Field(min_length=1)
    toolArguments: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    riskLevel: Literal["L1", "L2", "L3"] = "L1"
    requiresConfirmation: bool = False
    waitCondition: CopilotTaskWaitCondition | None = None


class CopilotTaskPlan(BaseModel):
    title: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    summary: str = ""
    steps: list[CopilotTaskPlanStep] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("steps")
    @classmethod
    def unique_steps(cls, steps: list[CopilotTaskPlanStep]):
        ids = [step.clientStepId for step in steps]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_step_id")
        return steps


class CopilotTaskPlanRequest(BaseModel):
    goal: str = Field(min_length=1)
    workspace_id: UUID | None = None
    conversation_id: str | None = None


class CopilotTaskCreate(BaseModel):
    plan: CopilotTaskPlan
    workspace_id: UUID | None = None
    conversation_id: str | None = None


class CopilotTaskStepOut(BaseModel):
    id: UUID
    task_id: UUID
    step_order: int
    client_step_id: str | None
    title: str
    description: str | None
    tool_name: str
    tool_arguments: dict[str, Any]
    dependencies: list[str]
    wait_condition: dict[str, Any] | None
    risk_level: str
    requires_confirmation: bool
    status: StepStatus | str
    retry_count: int
    max_retries: int
    idempotency_key: str
    output: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    claimed_by: str | None
    claimed_at: datetime | None
    lease_expires_at: datetime | None
    heartbeat_at: datetime | None
    execution_attempt: int
    next_retry_at: datetime | None
    next_check_at: datetime | None
    check_interval_seconds: int
    timeout_at: datetime | None
    last_observed_status: str | None
    check_count: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CopilotTaskEventOut(BaseModel):
    id: UUID
    event_id: int
    tenant_id: UUID
    workspace_id: UUID | None
    task_id: UUID
    step_id: UUID | None
    event_type: str
    payload: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class CopilotTaskOut(BaseModel):
    id: UUID
    tenant_id: UUID
    workspace_id: UUID | None
    user_id: UUID
    conversation_id: str | None
    title: str
    user_goal: str
    plan_version: int
    status: TaskStatus | str
    current_step_id: UUID | None
    progress_percent: int
    plan: dict[str, Any]
    warnings: list[str]
    result_summary: str | None
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    created_at: datetime
    updated_at: datetime
    steps: list[CopilotTaskStepOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class CopilotTaskActionIn(BaseModel):
    reason: str | None = None
    publish_confirmed: bool = False


class AgentTestCase(BaseModel):
    id: str
    question: str
    expectedIntent: str | None = None
    expectedKeywords: list[str] = Field(default_factory=list)
    requireCitation: bool = True
    forbiddenBehaviors: list[str] = Field(default_factory=list)
    severity: Literal["low", "medium", "high"] = "medium"


class PreflightCheckItem(BaseModel):
    code: str
    title: str
    status: Literal["passed", "warning", "blocking"]
    message: str
    remediation: dict[str, Any] | None = None
