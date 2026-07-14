from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, get_current_auth, require_perm
from app.core.database import get_db
from app.models import AgentTemplate, Model
from app.orchestrator import build_agent_context, dispatch_single_agent
from app.schemas import (
    AgentCreate,
    AgentOut,
    AgentRunIn,
    AgentRunOut,
    AgentTemplateOut,
    AgentUpdate,
    ContextBuildIn,
    ContextBuildOut,
    ModelOut,
)
from app.services import archive_agent, create_agent, ensure_agent_templates, get_agent, list_agents, publish_agent, update_agent
from app.services.audit_service import write_audit

router = APIRouter(tags=["agents"])


def agent_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        body = {"error": {"code": code, "message": getattr(exc, "detail", code)}}
        if code in {"maas_timeout"}:
            return HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=body)
        if code in {"dependency_unavailable"}:
            return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=body)
        if code in {"maas_call_failed", "maas_stream_failed"}:
            return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=body)
        if code == "no_active_model_channel":
            return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=body)
        if code.endswith("_not_found"):
            return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=body)
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=body)
    if detail.endswith("_exists"):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    if detail in {"agent_template_type_mismatch"}:
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    if detail in {"tool_not_bound"}:
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    if detail in {"maas_call_failed"}:
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
    if detail == "no_active_model_channel":
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    if detail.endswith("_not_found") or detail.startswith(("kb_not_found:", "tool_not_found:")):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


@router.get("/agent-templates", response_model=list[AgentTemplateOut], summary="List agent templates")
async def list_agent_templates(
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> list:
    await ensure_agent_templates(db)
    await db.commit()
    result = await db.execute(select(AgentTemplate).order_by(AgentTemplate.type, AgentTemplate.name))
    return list(result.scalars().all())


@router.get("/models", response_model=list[ModelOut], summary="List models")
async def list_models(
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> list:
    result = await db.execute(select(Model).order_by(Model.type, Model.name))
    return list(result.scalars().all())


@router.get("/agents", response_model=list[AgentOut], summary="List agents")
async def list_agent_api(
    status_filter: str | None = Query(default=None, alias="status"),
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> list[AgentOut]:
    return await list_agents(db, tenant_id=auth.tenant_id, status=status_filter)


@router.post("/agents", response_model=AgentOut, status_code=status.HTTP_201_CREATED, summary="Create agent")
async def create_agent_api(
    payload: AgentCreate,
    request: Request,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
) -> AgentOut:
    try:
        agent = await create_agent(db, tenant_id=auth.tenant_id, user_id=auth.user_id, payload=payload)
    except ValueError as exc:
        raise agent_error(exc) from exc
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="agent.create",
        resource_type="agent",
        resource_id=agent.id,
        detail={"name": agent.name, "type": agent.type},
        request=request,
    )
    return agent


@router.get("/agents/{agent_id}", response_model=AgentOut, summary="Get agent")
async def get_agent_api(
    agent_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> AgentOut:
    agent = await get_agent(db, tenant_id=auth.tenant_id, agent_id=agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent_not_found")
    return agent


@router.patch("/agents/{agent_id}", response_model=AgentOut, summary="Update agent")
async def update_agent_api(
    agent_id: UUID,
    payload: AgentUpdate,
    request: Request,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
) -> AgentOut:
    try:
        agent = await update_agent(db, tenant_id=auth.tenant_id, agent_id=agent_id, payload=payload)
    except ValueError as exc:
        raise agent_error(exc) from exc
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="agent.update",
        resource_type="agent",
        resource_id=agent.id,
        detail={"fields": sorted(payload.model_dump(exclude_unset=True).keys())},
        request=request,
    )
    return agent


@router.post("/agents/{agent_id}/publish", response_model=AgentOut, summary="Publish agent")
async def publish_agent_api(
    agent_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
) -> AgentOut:
    agent = await publish_agent(db, tenant_id=auth.tenant_id, agent_id=agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="agent.publish",
        resource_type="agent",
        resource_id=agent.id,
        detail={"name": agent.name, "type": agent.type},
        request=request,
    )
    return agent


@router.post("/agents/{agent_id}/context", response_model=ContextBuildOut, summary="Build agent context")
async def build_agent_context_api(
    agent_id: UUID,
    payload: ContextBuildIn,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> ContextBuildOut:
    try:
        context = await build_agent_context(
            db,
            tenant_id=auth.tenant_id,
            agent_id=agent_id,
            query=payload.query,
            conversation_id=payload.conversation_id,
            workspace_id=payload.workspace_id,
            max_tokens=payload.max_tokens,
            history_limit=payload.history_limit,
            top_k=payload.top_k,
            score_threshold=payload.score_threshold,
            match_type=payload.match_type,
        )
    except ValueError as exc:
        raise agent_error(exc) from exc
    if context is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent_not_found")
    return context


@router.post("/agents/{agent_id}/run", response_model=AgentRunOut, summary="Run agent")
async def run_agent_api(
    agent_id: UUID,
    payload: AgentRunIn,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> AgentRunOut:
    try:
        result = await dispatch_single_agent(
            db,
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            agent_id=agent_id,
                payload=payload,
            )
    except ValueError as exc:
        raise agent_error(exc) from exc
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent_not_found")
    return result


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Archive agent")
async def delete_agent_api(
    agent_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
) -> None:
    archived = await archive_agent(db, tenant_id=auth.tenant_id, agent_id=agent_id)
    if not archived:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="agent.archive",
        resource_type="agent",
        resource_id=agent_id,
        request=request,
    )
