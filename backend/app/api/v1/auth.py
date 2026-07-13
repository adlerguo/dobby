from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, get_current_auth, get_permission_codes, get_role_codes
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_jwt, decode_jwt, verify_password
from app.models import Tenant, User
from app.schemas import LoginIn, MeOut, RefreshIn, TokenOut
from app.services.audit_service import write_audit

router = APIRouter(prefix="/auth", tags=["auth"])


def build_token_out(user: User, roles: list[str]) -> TokenOut:
    payload = {
        "user_id": str(user.id),
        "tenant_id": str(user.tenant_id),
        "roles": roles,
    }
    access_token = create_jwt(
        {**payload, "typ": "access"},
        secret=settings.jwt_secret,
        ttl_seconds=settings.jwt_access_ttl,
    )
    refresh_token = create_jwt(
        {**payload, "typ": "refresh"},
        secret=settings.jwt_secret,
        ttl_seconds=settings.jwt_refresh_ttl,
    )
    return TokenOut(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.jwt_access_ttl,
    )


@router.post("/login", response_model=TokenOut, summary="Login")
async def login(payload: LoginIn, request: Request, db: AsyncSession = Depends(get_db)) -> TokenOut:
    stmt = (
        select(User)
        .join(Tenant, Tenant.id == User.tenant_id)
        .where(
            Tenant.code == payload.tenant_code,
            Tenant.status == "active",
            User.username == payload.username,
            User.status == "active",
        )
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")

    roles = await get_role_codes(db, user.id)
    await write_audit(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="auth.login",
        resource_type="auth",
        resource_id=user.id,
        detail={"username": user.username, "tenant_code": payload.tenant_code},
        request=request,
    )
    return build_token_out(user, roles)


@router.post("/refresh", response_model=TokenOut, summary="Refresh token")
async def refresh(payload: RefreshIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    try:
        token_payload = decode_jwt(payload.refresh_token, secret=settings.jwt_secret)
        if token_payload.get("typ") != "refresh":
            raise ValueError("wrong_token_type")
        user_id = UUID(token_payload["user_id"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_refresh_token") from None

    user = await db.get(User, user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="inactive_user")

    roles = await get_role_codes(db, user.id)
    return build_token_out(user, roles)


@router.get("/me", response_model=MeOut, summary="Current user")
async def me(auth: AuthContext = Depends(get_current_auth), db: AsyncSession = Depends(get_db)) -> MeOut:
    return MeOut(
        user_id=auth.user.id,
        tenant_id=auth.tenant.id,
        username=auth.user.username,
        display_name=auth.user.display_name,
        roles=auth.roles,
        permissions=await get_permission_codes(db, auth.user.id),
    )
