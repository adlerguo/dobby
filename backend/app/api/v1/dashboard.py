from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_perm
from app.core.database import get_db
from app.schemas import DashboardExecutiveOut, DashboardOverviewOut, DashboardTechnicalOut, TraceDetailOut
from app.services import (
    build_dashboard_overview,
    build_executive_dashboard,
    build_technical_dashboard,
    build_trace_detail,
)

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/overview", response_model=DashboardOverviewOut, summary="Get dashboard overview")
async def get_dashboard_overview(
    view: str = Query(default="executive", pattern="^(executive|technical)$"),
    period_days: int = Query(default=7, ge=1, le=90),
    auth: AuthContext = Depends(require_perm("dashboard:view")),
    db: AsyncSession = Depends(get_db),
) -> DashboardOverviewOut:
    return await build_dashboard_overview(db, tenant_id=auth.tenant_id, view=view, period_days=period_days)


@router.get("/dashboard/technical", response_model=DashboardTechnicalOut, summary="Get technical dashboard")
async def get_technical_dashboard(
    period_days: int = Query(default=7, ge=1, le=90),
    auth: AuthContext = Depends(require_perm("dashboard:view")),
    db: AsyncSession = Depends(get_db),
) -> DashboardTechnicalOut:
    return await build_technical_dashboard(db, tenant_id=auth.tenant_id, period_days=period_days)


@router.get("/dashboard/executive", response_model=DashboardExecutiveOut, summary="Get executive dashboard")
async def get_executive_dashboard(
    period_days: int = Query(default=7, ge=1, le=90),
    auth: AuthContext = Depends(require_perm("dashboard:view")),
    db: AsyncSession = Depends(get_db),
) -> DashboardExecutiveOut:
    return await build_executive_dashboard(db, tenant_id=auth.tenant_id, period_days=period_days)


@router.get("/traces/{cid}", response_model=TraceDetailOut, summary="Get trace detail")
async def get_trace_detail(
    cid: UUID,
    auth: AuthContext = Depends(require_perm("dashboard:view")),
    db: AsyncSession = Depends(get_db),
) -> TraceDetailOut:
    trace_detail = await build_trace_detail(db, tenant_id=auth.tenant_id, cid=cid)
    if trace_detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="trace_not_found")
    return trace_detail
