from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


AGENT_TYPES = {
    "qa",
    "nl2data",
    "doc_gen",
    "doc_check",
    "analysis",
    "file_parse",
    "extract",
    "file_diff",
    "recommend",
    "retrieve",
    "custom",
    "workflow_approval",
    "form_intake",
    "policy_interpret",
    "task_planner",
    "ops_assistant",
}


class AgentTemplateOut(BaseModel):
    id: UUID
    type: str
    name: str
    default_config: dict[str, Any]
    builtin: bool | None

    model_config = {"from_attributes": True}


class AgentCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1)
    type: str = Field(pattern=r"^(qa|nl2data|doc_gen|doc_check|analysis|file_parse|extract|file_diff|recommend|retrieve|custom|workflow_approval|form_intake|policy_interpret|task_planner|ops_assistant)$")
    template_id: UUID | None = None
    persona: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    model_id: UUID | None = None
    kb_ids: list[UUID] = Field(default_factory=list)
    tool_ids: list[UUID] = Field(default_factory=list)


class AgentUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str | None = Field(default=None, min_length=1)
    template_id: UUID | None = None
    persona: str | None = None
    config: dict[str, Any] | None = None
    model_id: UUID | None = None
    kb_ids: list[UUID] | None = None
    tool_ids: list[UUID] | None = None
    status: str | None = Field(default=None, pattern=r"^(active|disabled|draft|archived)$")


class AgentOut(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    type: str
    template_id: UUID | None
    persona: str | None
    config: dict[str, Any]
    model_id: UUID | None
    status: str | None
    created_by: UUID | None
    kb_ids: list[UUID]
    tool_ids: list[UUID]

    model_config = {"from_attributes": True}


class ModelOut(BaseModel):
    id: UUID
    name: str
    provider: str | None
    type: str

    model_config = {"from_attributes": True}
