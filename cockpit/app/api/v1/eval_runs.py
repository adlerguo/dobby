from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import CurrentUser, get_current_user
from app.core.database import get_db
from app.models.eval import EvalRun
from app.schemas.eval import EvalRunCreate, EvalRunProgress, EvalRunRead
from app.services.eval_runner import create_eval_run

router = APIRouter(prefix="/eval_runs", tags=["eval_runs"])


@router.post("", response_model=EvalRunRead)
async def trigger_eval_run(
    payload: EvalRunCreate,
    session: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> EvalRun:
    try:
        return await create_eval_run(session, payload, current_user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[EvalRunRead])
async def list_eval_runs(
    session: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
) -> list[EvalRun]:
    result = await session.execute(
        select(EvalRun).options(selectinload(EvalRun.items)).order_by(EvalRun.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{run_id}", response_model=EvalRunRead)
async def get_eval_run(
    run_id: UUID,
    session: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
) -> EvalRun:
    item = await session.get(EvalRun, run_id, options=[selectinload(EvalRun.items)])
    if not item:
        raise HTTPException(status_code=404, detail="eval_run_not_found")
    return item


@router.get("/{run_id}/progress", response_model=EvalRunProgress)
async def get_eval_run_progress(
    run_id: UUID,
    session: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
) -> EvalRun:
    item = await session.get(EvalRun, run_id)
    if not item:
        raise HTTPException(status_code=404, detail="eval_run_not_found")
    return item
