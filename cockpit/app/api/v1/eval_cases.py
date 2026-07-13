from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, get_current_user
from app.core.database import get_db
from app.models.eval import EvalCase
from app.schemas.eval import EvalCaseCreate, EvalCaseRead, EvalCaseUpdate

router = APIRouter(prefix="/eval_cases", tags=["eval_cases"])


@router.get("", response_model=list[EvalCaseRead])
async def list_eval_cases(
    target_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
) -> list[EvalCase]:
    stmt = select(EvalCase).order_by(EvalCase.created_at.desc())
    if target_id:
        stmt = stmt.where(EvalCase.target_id == target_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=EvalCaseRead)
async def create_eval_case(
    payload: EvalCaseCreate,
    session: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> EvalCase:
    item = EvalCase(**payload.model_dump(), created_by=current_user.user_id)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.get("/{case_id}", response_model=EvalCaseRead)
async def get_eval_case(
    case_id: UUID,
    session: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
) -> EvalCase:
    item = await session.get(EvalCase, case_id)
    if not item:
        raise HTTPException(status_code=404, detail="eval_case_not_found")
    return item


@router.put("/{case_id}", response_model=EvalCaseRead)
async def update_eval_case(
    case_id: UUID,
    payload: EvalCaseUpdate,
    session: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
) -> EvalCase:
    item = await session.get(EvalCase, case_id)
    if not item:
        raise HTTPException(status_code=404, detail="eval_case_not_found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await session.commit()
    await session.refresh(item)
    return item


@router.delete("/{case_id}")
async def delete_eval_case(
    case_id: UUID,
    session: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
) -> dict[str, bool]:
    item = await session.get(EvalCase, case_id)
    if not item:
        raise HTTPException(status_code=404, detail="eval_case_not_found")
    await session.delete(item)
    await session.commit()
    return {"ok": True}
