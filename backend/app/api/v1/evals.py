from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_perm
from app.core.database import get_db
from app.schemas import (
    EvalCaseCreate,
    EvalCaseOut,
    EvalCaseUpdate,
    EvalReportOut,
    EvalRunOut,
    EvalRunRequest,
    ExperienceCreate,
    ExperienceOut,
)
from app.services.eval_service import (
    create_eval_case,
    create_experience,
    delete_eval_case,
    eval_run_out,
    get_eval_case,
    list_eval_cases,
    list_eval_runs,
    run_agent_eval,
    search_experiences,
    update_eval_case,
)
from app.services.audit_service import write_audit

router = APIRouter(tags=["evals"])


def eval_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    if detail.endswith("_not_found"):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    if detail in {"maas_call_failed"}:
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


@router.get("/eval-cases", response_model=list[EvalCaseOut], summary="List eval cases")
async def list_eval_case_api(
    scene: str | None = Query(default=None),
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
) -> list:
    return await list_eval_cases(db, tenant_id=auth.tenant_id, scene=scene)


@router.post("/eval-cases", response_model=EvalCaseOut, status_code=status.HTTP_201_CREATED, summary="Create eval case")
async def create_eval_case_api(
    payload: EvalCaseCreate,
    request: Request,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
):
    case = await create_eval_case(db, tenant_id=auth.tenant_id, payload=payload)
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="eval_case.create",
        resource_type="eval_case",
        resource_id=case.id,
        detail={"scene": case.scene, "assert_type": case.assert_type},
        request=request,
    )
    return case


@router.get("/eval-cases/{case_id}", response_model=EvalCaseOut, summary="Get eval case")
async def get_eval_case_api(
    case_id: UUID,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
):
    case = await get_eval_case(db, tenant_id=auth.tenant_id, case_id=case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="eval_case_not_found")
    return case


@router.patch("/eval-cases/{case_id}", response_model=EvalCaseOut, summary="Update eval case")
async def update_eval_case_api(
    case_id: UUID,
    payload: EvalCaseUpdate,
    request: Request,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
):
    case = await update_eval_case(db, tenant_id=auth.tenant_id, case_id=case_id, payload=payload)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="eval_case_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="eval_case.update",
        resource_type="eval_case",
        resource_id=case.id,
        detail={"fields": sorted(payload.model_dump(exclude_unset=True).keys())},
        request=request,
    )
    return case


@router.delete("/eval-cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete eval case")
async def delete_eval_case_api(
    case_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
) -> None:
    deleted = await delete_eval_case(db, tenant_id=auth.tenant_id, case_id=case_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="eval_case_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="eval_case.delete",
        resource_type="eval_case",
        resource_id=case_id,
        request=request,
    )


@router.post("/agents/{agent_id}/eval", response_model=EvalReportOut, summary="Run agent eval")
async def run_agent_eval_api(
    agent_id: UUID,
    payload: EvalRunRequest,
    request: Request,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
) -> EvalReportOut:
    try:
        report = await run_agent_eval(
            db,
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            agent_id=agent_id,
            payload=payload,
        )
    except ValueError as exc:
        raise eval_error(exc) from exc
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="agent.eval",
        resource_type="agent",
        resource_id=agent_id,
        detail={"total": report.total, "passed": report.passed, "failed": report.failed, "pass_rate": report.pass_rate},
        request=request,
    )
    return report


@router.get("/agents/{agent_id}/eval-runs", response_model=list[EvalRunOut], summary="List agent eval runs")
async def list_agent_eval_runs_api(
    agent_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
) -> list[EvalRunOut]:
    runs = await list_eval_runs(db, tenant_id=auth.tenant_id, agent_id=agent_id, limit=limit)
    return [eval_run_out(run) for run in runs]


@router.post(
    "/agents/{agent_id}/experiences",
    response_model=ExperienceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create agent experience",
)
async def create_agent_experience_api(
    agent_id: UUID,
    payload: ExperienceCreate,
    request: Request,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
):
    experience = await create_experience(db, tenant_id=auth.tenant_id, agent_id=agent_id, payload=payload)
    if experience is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="experience.create",
        resource_type="experience",
        resource_id=experience.id,
        detail={"agent_id": str(agent_id), "scene": experience.scene},
        request=request,
    )
    return experience


@router.get("/agents/{agent_id}/experiences", response_model=list[ExperienceOut], summary="Search agent experiences")
async def search_agent_experiences_api(
    agent_id: UUID,
    query: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
) -> list:
    return await search_experiences(
        db,
        tenant_id=auth.tenant_id,
        agent_id=agent_id,
        query=query,
        limit=limit,
    )
