from uuid import UUID

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    model_config = {"extra": "forbid"}

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    tenant_code: str = Field(default="default", min_length=1)


class RefreshIn(BaseModel):
    model_config = {"extra": "forbid"}

    refresh_token: str = Field(min_length=1)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class MeOut(BaseModel):
    user_id: UUID
    tenant_id: UUID
    username: str
    display_name: str | None
    roles: list[str]
    permissions: list[str]
