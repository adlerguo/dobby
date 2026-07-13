from typing import Any
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field


class ToolCreate(BaseModel):
    model_config = {"extra": "forbid", "populate_by_name": True}

    name: str = Field(min_length=1)
    type: str = Field(pattern=r"^(http|code|builtin)$")
    tool_schema: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("schema", "tool_schema"),
        serialization_alias="schema",
    )
    config: dict[str, Any] = Field(default_factory=dict)


class ToolUpdate(BaseModel):
    model_config = {"extra": "forbid", "populate_by_name": True}

    name: str | None = Field(default=None, min_length=1)
    tool_schema: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("schema", "tool_schema"),
        serialization_alias="schema",
    )
    config: dict[str, Any] | None = None
    status: str | None = Field(default=None, pattern=r"^(active|disabled|draft|archived)$")


class ToolOut(BaseModel):
    model_config = {"from_attributes": True, "populate_by_name": True}

    id: UUID
    tenant_id: UUID
    name: str
    type: str
    tool_schema: dict[str, Any] = Field(
        validation_alias=AliasChoices("schema", "tool_schema"),
        serialization_alias="schema",
    )
    config: dict[str, Any]
    status: str | None


class ToolRunIn(BaseModel):
    model_config = {"extra": "forbid"}

    input: dict[str, Any] = Field(default_factory=dict)


class ToolRunOut(BaseModel):
    tool_id: UUID
    type: str
    status: str
    output: dict[str, Any]
