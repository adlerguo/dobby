from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, get_current_user
from app.core.database import get_db
from app.models.eval import Experience
from app.schemas.experience import ExperienceCreate, ExperienceRead, ExperienceUpdate

router = APIRouter(prefix="/experiences", tags=["experiences"])


@router.get("", response_model=list[ExperienceRead])
async def list_experiences(
    keyword: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
) -> list[Experience]:
    stmt = select(Experience).order_by(Experience.created_at.desc())
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Experience.title.ilike(like), Experience.content.ilike(like)))
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=ExperienceRead)
async def create_experience(
    payload: ExperienceCreate,
    session: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> Experience:
    item = Experience(**payload.model_dump(), created_by=current_user.user_id)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.put("/{experience_id}", response_model=ExperienceRead)
async def update_experience(
    experience_id: UUID,
    payload: ExperienceUpdate,
    session: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
) -> Experience:
    item = await session.get(Experience, experience_id)
    if not item:
        raise HTTPException(status_code=404, detail="experience_not_found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await session.commit()
    await session.refresh(item)
    return item


@router.delete("/{experience_id}")
async def delete_experience(
    experience_id: UUID,
    session: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
) -> dict[str, bool]:
    item = await session.get(Experience, experience_id)
    if not item:
        raise HTTPException(status_code=404, detail="experience_not_found")
    await session.delete(item)
    await session.commit()
    return {"ok": True}
