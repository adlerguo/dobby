from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


ComputerUseSessionStatus = Literal[
    "pending_consent",
    "initializing",
    "running",
    "waiting_user",
    "paused",
    "succeeded",
    "failed",
    "stopped",
    "expired",
]


class ComputerUseTargetCreate(BaseModel):
    model_config = {"extra": "forbid"}

    workspace_id: UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    allowed_domains: list[str] = Field(default_factory=list)
    allowed_url_patterns: list[str] = Field(default_factory=list)
    denied_url_patterns: list[str] = Field(default_factory=list)
    allow_navigation: bool = True
    max_session_minutes: int = Field(default=15, ge=1, le=60)
    max_actions: int = Field(default=20, ge=1, le=100)
    enabled: bool = False


class ComputerUseTargetOut(BaseModel):
    id: UUID
    tenant_id: UUID
    workspace_id: UUID | None = None
    name: str
    description: str | None = None
    allowed_domains: list[str] = Field(default_factory=list)
    allowed_url_patterns: list[str] = Field(default_factory=list)
    denied_url_patterns: list[str] = Field(default_factory=list)
    allow_navigation: bool
    allow_form_fill: bool
    allow_submit: bool
    allow_upload: bool
    allow_download: bool
    allow_login: bool
    allow_persistent_session: bool
    max_session_minutes: int
    max_actions: int
    enabled: bool
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ComputerUseConsentIn(BaseModel):
    model_config = {"extra": "forbid"}

    target_id: UUID
    user_goal: str = Field(min_length=1, max_length=1000)
    start_url: str = Field(min_length=1, max_length=2000)
    workspace_id: UUID | None = None
    conversation_id: str | None = None
    approved_plan: dict[str, Any] = Field(default_factory=dict)
    consent_approved: bool = False


class ComputerUseActionOut(BaseModel):
    id: UUID
    session_id: UUID
    sequence: int
    action_type: str
    target_description: str | None = None
    before_url: str | None = None
    after_url: str | None = None
    before_screenshot_id: str | None = None
    after_screenshot_id: str | None = None
    status: str
    risk_level: str
    requires_confirmation: bool
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class ComputerUseSessionOut(BaseModel):
    id: UUID
    tenant_id: UUID
    workspace_id: UUID | None = None
    user_id: UUID
    task_id: UUID | None = None
    conversation_id: str | None = None
    target_id: UUID
    status: ComputerUseSessionStatus
    execution_mode: str
    current_url: str | None = None
    current_title: str | None = None
    allowed_domains: list[str] = Field(default_factory=list)
    user_goal: str
    approved_plan: dict[str, Any] = Field(default_factory=dict)
    risk_level: str
    started_at: datetime | None = None
    last_activity_at: datetime | None = None
    expires_at: datetime | None = None
    paused_at: datetime | None = None
    completed_at: datetime | None = None
    stopped_at: datetime | None = None
    stop_reason: str | None = None
    takeover_required: bool
    browser_context_ref: str | None = None
    security_events: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ComputerUseCaptureIn(BaseModel):
    model_config = {"extra": "forbid"}

    current_url: str | None = Field(default=None, max_length=2000)
    page_title: str | None = Field(default=None, max_length=300)
    visible_text: str | None = Field(default=None, max_length=8000)


class ComputerUsePageState(BaseModel):
    url: str
    title: str | None = None
    summary: str
    interactive_elements: list[dict[str, Any]] = Field(default_factory=list)
    screenshot_id: str | None = None
    risk_flags: list[str] = Field(default_factory=list)


class ComputerUseCaptureOut(BaseModel):
    session: ComputerUseSessionOut
    action: ComputerUseActionOut
    page_state: ComputerUsePageState


class ComputerUseStatusOut(BaseModel):
    enabled: bool
    reason: str | None = None
    max_session_minutes: int
    max_actions: int
