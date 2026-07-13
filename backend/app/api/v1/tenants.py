from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_perm
from app.core.database import get_db
from app.models import Tenant
from app.schemas import TenantCreate, TenantOut
from app.services import ensure_roles_for_tenant
from app.services.audit_service import write_audit

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("", response_model=list[TenantOut], summary="List tenants")
async def list_tenants(
    _: AuthContext = Depends(require_perm("tenant:view")),
    db: AsyncSession = Depends(get_db),
) -> list[Tenant]:
    result = await db.execute(select(Tenant).order_by(Tenant.created_at.desc()))
    return list(result.scalars().all())


@router.post("", response_model=TenantOut, status_code=status.HTTP_201_CREATED, summary="Create tenant")
async def create_tenant(
    payload: TenantCreate,
    request: Request,
    auth: AuthContext = Depends(require_perm("tenant:create")),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    result = await db.execute(select(Tenant).where(Tenant.code == payload.code))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="tenant_code_exists")

    tenant = Tenant(name=payload.name, code=payload.code, status="active")
    db.add(tenant)
    await db.flush()
    await ensure_roles_for_tenant(db, tenant.id)
    await db.commit()
    await db.refresh(tenant)
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="tenant.create",
        resource_type="tenant",
        resource_id=tenant.id,
        detail={"name": tenant.name, "code": tenant.code},
        request=request,
    )
    return tenant
