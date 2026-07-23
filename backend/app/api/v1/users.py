from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_perm
from app.core.database import get_db
from app.core.security import hash_password
from app.models import User
from app.schemas import AssignRolesIn, AssignRolesOut, UserCreate, UserOut, UserUpdate
from app.services import assign_role_codes
from app.services.audit_service import write_audit
from app.services.validation import detail_from_integrity_error, normalize_unique_text

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut], summary="List users")
async def list_users(
    auth: AuthContext = Depends(require_perm("user:view")),
    db: AsyncSession = Depends(get_db),
) -> list[User]:
    result = await db.execute(
        select(User)
        .where(User.tenant_id == auth.tenant_id)
        .order_by(User.created_at.desc())
    )
    return list(result.scalars().all())


@router.post(
    "",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create user",
)
async def create_user(
    payload: UserCreate,
    request: Request,
    auth: AuthContext = Depends(require_perm("user:create")),
    db: AsyncSession = Depends(get_db),
) -> User:
    result = await db.execute(
        select(User).where(
            User.tenant_id == auth.tenant_id,
            func.lower(func.btrim(User.username))
            == normalize_unique_text(payload.username),
        )
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="username_exists"
        )

    user = User(
        tenant_id=auth.tenant_id,
        username=payload.username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        email=payload.email,
        status="active",
    )
    try:
        db.add(user)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail_from_integrity_error(exc, "username_exists"),
        ) from exc
    await db.refresh(user)
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="user.create",
        resource_type="user",
        resource_id=user.id,
        detail={
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email,
        },
        request=request,
    )
    return user


@router.get("/{user_id}", response_model=UserOut, summary="Get user")
async def get_user(
    user_id: UUID,
    auth: AuthContext = Depends(require_perm("user:view")),
    db: AsyncSession = Depends(get_db),
) -> User:
    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == auth.tenant_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found"
        )
    return user


@router.patch("/{user_id}", response_model=UserOut, summary="Update user")
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    request: Request,
    auth: AuthContext = Depends(require_perm("user:update")),
    db: AsyncSession = Depends(get_db),
) -> User:
    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == auth.tenant_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found"
        )

    values = payload.model_dump(exclude_unset=True)
    if "username" in values:
        result = await db.execute(
            select(User.id).where(
                User.tenant_id == auth.tenant_id,
                User.id != user_id,
                func.lower(func.btrim(User.username))
                == normalize_unique_text(values["username"]),
            )
        )
        if result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="username_exists"
            )
    for key, value in values.items():
        setattr(user, key, value)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail_from_integrity_error(exc, "username_exists"),
        ) from exc
    await db.refresh(user)
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="user.update",
        resource_type="user",
        resource_id=user.id,
        detail={"fields": sorted(values.keys())},
        request=request,
    )
    return user


@router.post("/{user_id}/roles", response_model=AssignRolesOut, summary="Assign roles")
async def assign_roles(
    user_id: UUID,
    payload: AssignRolesIn,
    request: Request,
    auth: AuthContext = Depends(require_perm("user:assign_role")),
    db: AsyncSession = Depends(get_db),
) -> AssignRolesOut:
    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == auth.tenant_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found"
        )

    try:
        role_codes = await assign_role_codes(
            db, user.id, auth.tenant_id, payload.role_codes
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    await db.commit()
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="user.assign_roles",
        resource_type="user",
        resource_id=user.id,
        detail={"role_codes": role_codes},
        request=request,
    )
    return AssignRolesOut(user_id=user.id, role_codes=role_codes)
