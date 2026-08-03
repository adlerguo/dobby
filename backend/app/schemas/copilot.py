from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CopilotToolOut(BaseModel):
    name: str
    description: str
    category: str
    risk_level: Literal["L0", "L1", "L2", "L3"]
    requires_confirmation: bool
    permission: list[str]
    input_schema: dict[str, Any]


class CopilotExecuteIn(BaseModel):
    model_config = {"extra": "forbid"}

    tool: str = Field(min_length=1)
    input: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = False
    conversation_id: str | None = None
    workspace_id: str | None = None
    preview: dict[str, Any] | None = None


class CopilotExecuteOut(BaseModel):
    tool: str
    status: Literal["success", "failed"]
    message: str
    target_type: str | None = None
    target_id: UUID | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    audit: dict[str, Any] = Field(default_factory=dict)
