from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class DashboardMetricOut(BaseModel):
    key: str
    label: str
    value: int | float | str
    unit: str | None = None
    description: str | None = None


class DashboardOverviewOut(BaseModel):
    view: str
    period_days: int
    generated_at: datetime
    metrics: list[DashboardMetricOut]
    highlights: list[str]
    technical: dict[str, Any]
    executive: dict[str, Any]


class DashboardTechnicalOut(BaseModel):
    period_days: int
    generated_at: datetime
    summary: dict[str, Any]
    spans_by_type: dict[str, int]
    spans_by_status: dict[str, int]
    latency: dict[str, int | float | None]
    token_usage: dict[str, int]
    top_agents: list[dict[str, Any]]
    recent_errors: list[dict[str, Any]]
    recent_runs: list[dict[str, Any]]


class DashboardExecutiveOut(BaseModel):
    period_days: int
    generated_at: datetime
    headline: str
    scorecards: list[DashboardMetricOut]
    business_mix: list[dict[str, Any]]
    adoption: list[dict[str, Any]]
    takeaways: list[str]


class TraceSpanOut(BaseModel):
    id: UUID
    parent_id: UUID | None
    conversation_id: UUID | None
    agent_id: UUID | None
    agent_name: str | None = None
    span_type: str | None
    name: str | None
    status: str | None
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    tokens: int | None
    latency_ms: int | None
    created_at: datetime


class TraceDetailOut(BaseModel):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID | None
    title: str | None
    root_trace_id: UUID | None
    status: str | None
    summary: dict[str, Any]
    spans: list[TraceSpanOut]
    messages: list[dict[str, Any]]
