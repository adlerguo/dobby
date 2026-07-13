from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_perm
from app.core.database import get_db
from app.models import Permission, Role
from app.schemas import PermissionOut, RoleOut

router = APIRouter(tags=["rbac"])


@router.get("/roles", response_model=list[RoleOut], summary="List roles")
async def list_roles(
    auth: AuthContext = Depends(require_perm("role:view")),
    db: AsyncSession = Depends(get_db),
) -> list[Role]:
    result = await db.execute(select(Role).where(Role.tenant_id == auth.tenant_id).order_by(Role.code))
    return list(result.scalars().all())


@router.get("/permissions", response_model=list[PermissionOut], summary="List permissions")
async def list_permissions(
    _: AuthContext = Depends(require_perm("permission:view")),
    db: AsyncSession = Depends(get_db),
) -> list[Permission]:
    result = await db.execute(select(Permission).order_by(Permission.code))
    return list(result.scalars().all())
