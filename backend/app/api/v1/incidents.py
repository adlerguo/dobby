from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_perm
from app.core.database import get_db
from app.schemas import EvalCaseOut, IncidentOut, IncidentUpdate
from app.services.audit_service import write_audit
from app.services.incident_service import (
    incident_to_eval_case,
    list_incidents,
    update_incident,
)

router = APIRouter(tags=["incidents"])


@router.get("/incidents", response_model=list[IncidentOut], summary="List incidents")
async def list_incidents_api(
    status: str | None = Query(default=None),
    incident_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    agent_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
):
    return await list_incidents(
        db,
        tenant_id=auth.tenant_id,
        status=status,
        incident_type=incident_type,
        severity=severity,
        agent_id=agent_id,
        limit=limit,
    )


@router.patch(
    "/incidents/{incident_id}",
    response_model=IncidentOut,
    summary="Update incident",
)
async def update_incident_api(
    incident_id: UUID,
    payload: IncidentUpdate,
    request: Request,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
):
    incident = await update_incident(
        db,
        tenant_id=auth.tenant_id,
        incident_id=incident_id,
        payload=payload,
        user_id=auth.user_id,
    )
    if incident is None:
        raise HTTPException(status_code=404, detail="incident_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="incident.update",
        resource_type="incident",
        resource_id=incident_id,
        detail=payload.model_dump(exclude_unset=True),
        request=request,
    )
    return incident


@router.post(
    "/incidents/{incident_id}/to-eval-case",
    response_model=EvalCaseOut,
    summary="Convert incident to eval case",
)
async def incident_to_eval_case_api(
    incident_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
):
    case = await incident_to_eval_case(
        db, tenant_id=auth.tenant_id, incident_id=incident_id
    )
    if case is None:
        raise HTTPException(status_code=404, detail="incident_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="incident.to_eval_case",
        resource_type="incident",
        resource_id=incident_id,
        detail={"case_id": str(case.id)},
        request=request,
    )
    return case
