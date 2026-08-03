from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_perm
from app.core.database import get_db
from app.schemas import (
    SecurityEvalReportOut,
    SecurityEvalRequest,
    SecurityEvalTemplateOut,
)
from app.services.audit_service import write_audit
from app.services.security_eval_service import run_security_eval, security_templates

router = APIRouter(tags=["security-evals"])


@router.get(
    "/security-evals/templates",
    response_model=list[SecurityEvalTemplateOut],
    summary="List security eval templates",
)
async def security_eval_templates_api(
    auth: AuthContext = Depends(require_perm("agent:publish")),
):
    return security_templates()


@router.post(
    "/agents/{agent_id}/security-eval",
    response_model=SecurityEvalReportOut,
    summary="Run agent security eval",
)
async def run_security_eval_api(
    agent_id: UUID,
    payload: SecurityEvalRequest,
    request: Request,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
):
    report = await run_security_eval(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        agent_id=agent_id,
        payload=payload,
    )
    if report is None:
        raise HTTPException(status_code=404, detail="agent_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="security_eval.run",
        resource_type="agent",
        resource_id=agent_id,
        detail={
            "total": report.total,
            "passed": report.passed,
            "failed": report.failed,
            "pass_rate": report.pass_rate,
            "risk_level": report.risk_level,
        },
        request=request,
    )
    return report
