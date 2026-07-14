from uuid import UUID

from pydantic import BaseModel, Field


class TenantCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1)
    code: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    admin_username: str = Field(default="admin", min_length=1)
    admin_email: str | None = None
    admin_display_name: str | None = None


class TenantOut(BaseModel):
    id: UUID
    name: str
    code: str
    status: str

    model_config = {"from_attributes": True}


class InitialTenantAdminOut(BaseModel):
    id: UUID
    username: str
    display_name: str | None
    email: str | None
    temporary_password: str
    password_must_change: bool = True


class TenantProvisionOut(BaseModel):
    tenant: TenantOut
    initial_admin: InitialTenantAdminOut


class UserCreate(BaseModel):
    model_config = {"extra": "forbid"}

    username: str = Field(min_length=1)
    password: str = Field(min_length=8)
    display_name: str | None = None
    email: str | None = None


class UserUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    display_name: str | None = None
    email: str | None = None
    status: str | None = Field(default=None, pattern=r"^(active|disabled)$")


class UserOut(BaseModel):
    id: UUID
    tenant_id: UUID
    username: str
    display_name: str | None
    email: str | None
    status: str | None

    model_config = {"from_attributes": True}


class RoleOut(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    code: str

    model_config = {"from_attributes": True}


class PermissionOut(BaseModel):
    id: UUID
    code: str
    name: str | None
    module: str | None

    model_config = {"from_attributes": True}


class AssignRolesIn(BaseModel):
    model_config = {"extra": "forbid"}

    role_codes: list[str] = Field(min_length=1)


class AssignRolesOut(BaseModel):
    user_id: UUID
    role_codes: list[str]
