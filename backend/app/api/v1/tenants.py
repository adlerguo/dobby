import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_perm
from app.core.database import get_db
from app.core.security import hash_password
from app.models import Tenant, User
from app.schemas import InitialTenantAdminOut, TenantCreate, TenantOut, TenantProvisionOut
from app.services import assign_role_codes, ensure_roles_for_tenant
from app.services.audit_service import write_audit

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("", response_model=list[TenantOut], summary="List tenants")
async def list_tenants(
    _: AuthContext = Depends(require_perm("tenant:view")),
    db: AsyncSession = Depends(get_db),
) -> list[Tenant]:
    result = await db.execute(select(Tenant).order_by(Tenant.created_at.desc()))
    return list(result.scalars().all())


@router.post("", response_model=TenantProvisionOut, status_code=status.HTTP_201_CREATED, summary="Create tenant")
async def create_tenant(
    payload: TenantCreate,
    request: Request,
    auth: AuthContext = Depends(require_perm("tenant:create")),
    db: AsyncSession = Depends(get_db),
) -> TenantProvisionOut:
    if "super_admin" not in auth.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="super_admin_required")

    result = await db.execute(select(Tenant).where(Tenant.code == payload.code))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="tenant_code_exists")

    temporary_password = generate_temporary_password()
    tenant = Tenant(name=payload.name, code=payload.code, status="active")
    try:
        db.add(tenant)
        await db.flush()
        await ensure_roles_for_tenant(db, tenant.id)
        admin = User(
            tenant_id=tenant.id,
            username=payload.admin_username,
            password_hash=hash_password(temporary_password),
            display_name=payload.admin_display_name or "租户管理员",
            email=payload.admin_email,
            status="active",
        )
        # TODO: persist a first-login password reset flag when the user model supports it.
        db.add(admin)
        await db.flush()
        await assign_role_codes(db, admin.id, tenant.id, ["tenant_admin"])
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="tenant_admin_conflict") from exc
    except Exception:
        await db.rollback()
        raise

    await db.refresh(tenant)
    await db.refresh(admin)
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="tenant.create",
        resource_type="tenant",
        resource_id=tenant.id,
        detail={"name": tenant.name, "code": tenant.code, "initial_admin": admin.username},
        request=request,
    )
    return TenantProvisionOut(
        tenant=TenantOut.model_validate(tenant),
        initial_admin=InitialTenantAdminOut(
            id=admin.id,
            username=admin.username,
            display_name=admin.display_name,
            email=admin.email,
            temporary_password=temporary_password,
            password_must_change=True,
        ),
    )


def generate_temporary_password() -> str:
    return secrets.token_urlsafe(18)
