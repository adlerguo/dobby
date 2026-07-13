from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_jwt
from app.models import Permission, Role, RolePermission, Tenant, User, UserRole

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    user: User
    tenant: Tenant
    roles: list[str]
    permissions: list[str]

    @property
    def user_id(self) -> UUID:
        return self.user.id

    @property
    def tenant_id(self) -> UUID:
        return self.tenant.id


async def get_role_codes(db: AsyncSession, user_id: UUID) -> list[str]:
    stmt = (
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
        .order_by(Role.code)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_permission_codes(db: AsyncSession, user_id: UUID) -> list[str]:
    stmt = (
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user_id)
        .order_by(Permission.code)
        .distinct()
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_current_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated")

    try:
        payload = decode_jwt(credentials.credentials, secret=settings.jwt_secret)
        if payload.get("typ") != "access":
            raise ValueError("wrong_token_type")
        user_id = UUID(payload["user_id"])
        tenant_id = UUID(payload["tenant_id"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token") from None

    user = await db.get(User, user_id)
    tenant = await db.get(Tenant, tenant_id)
    if user is None or tenant is None or user.status != "active" or tenant.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="inactive_identity")
    if user.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="tenant_mismatch")

    roles = await get_role_codes(db, user.id)
    permissions = await get_permission_codes(db, user.id)
    return AuthContext(user=user, tenant=tenant, roles=roles, permissions=permissions)


async def get_current_user(auth: AuthContext = Depends(get_current_auth)) -> User:
    return auth.user


async def get_current_tenant(auth: AuthContext = Depends(get_current_auth)) -> Tenant:
    return auth.tenant


def require_perm(permission_code: str):
    async def dependency(auth: AuthContext = Depends(get_current_auth)) -> AuthContext:
        if "super_admin" in auth.roles or permission_code in auth.permissions:
            return auth
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="permission_denied")

    return dependency
