from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models import Agent, AgentTemplate, KnowledgeBase, Model, Tool
from app.repositories import AgentRepository
from app.schemas import AgentCreate, AgentOut, AgentUpdate
from app.services.validation import (
    detail_from_integrity_error,
    ensure_tenant_name_available,
)


async def create_agent(
    db: AsyncSession, *, tenant_id: UUID, user_id: UUID, payload: AgentCreate
) -> AgentOut:
    template = await get_template(db, payload.template_id)
    if payload.template_id is not None and template is None:
        raise NotFoundError(code="agent_template_not_found")
    if template is not None and template.type != payload.type:
        raise ValidationError(code="agent_template_type_mismatch")

    config = dict(template.default_config if template is not None else {})
    config.update(payload.config)
    persona = payload.persona or config.get("persona")

    await validate_bindings(
        db, tenant_id=tenant_id, kb_ids=payload.kb_ids, tool_ids=payload.tool_ids
    )
    if payload.model_id is not None:
        await validate_model(db, payload.model_id)
    try:
        await ensure_tenant_name_available(
            db,
            model=Agent,
            tenant_id=tenant_id,
            name=payload.name,
            detail="agent_name_exists",
        )
    except ValueError as exc:
        raise ConflictError(code=str(exc)) from exc

    repo = AgentRepository(db, tenant_id)
    agent = Agent(
        tenant_id=tenant_id,
        name=payload.name,
        type=payload.type,
        template_id=payload.template_id,
        persona=persona,
        config=config,
        model_id=payload.model_id,
        status="draft",
        created_by=user_id,
    )
    try:
        await repo.add(agent)
        await repo.replace_kbs(agent.id, payload.kb_ids)
        await repo.replace_tools(agent.id, payload.tool_ids)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            code=detail_from_integrity_error(exc, "agent_create_conflict")
        ) from exc
    await db.refresh(agent)
    return await agent_out(db, repo, agent)


async def list_agents(
    db: AsyncSession, *, tenant_id: UUID, status: str | None = None
) -> list[AgentOut]:
    repo = AgentRepository(db, tenant_id)
    agents = await repo.list_by_status(status)
    return [await agent_out(db, repo, agent) for agent in agents]


async def get_agent(
    db: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> AgentOut | None:
    repo = AgentRepository(db, tenant_id)
    agent = await repo.get_by_id(agent_id)
    if agent is None:
        return None
    return await agent_out(db, repo, agent)


async def update_agent(
    db: AsyncSession, *, tenant_id: UUID, agent_id: UUID, payload: AgentUpdate
) -> AgentOut | None:
    repo = AgentRepository(db, tenant_id)
    agent = await repo.get_by_id(agent_id)
    if agent is None:
        return None

    values = payload.model_dump(exclude_unset=True, exclude={"kb_ids", "tool_ids"})
    if payload.name is not None:
        try:
            await ensure_tenant_name_available(
                db,
                model=Agent,
                tenant_id=tenant_id,
                name=payload.name,
                detail="agent_name_exists",
                exclude_id=agent_id,
            )
        except ValueError as exc:
            raise ConflictError(code=str(exc)) from exc
    if payload.template_id is not None:
        template = await get_template(db, payload.template_id)
        if template is None:
            raise NotFoundError(code="agent_template_not_found")
        if template.type != agent.type:
            raise ValidationError(code="agent_template_type_mismatch")
    if payload.model_id is not None:
        await validate_model(db, payload.model_id)
    for key, value in values.items():
        setattr(agent, key, value)

    if payload.kb_ids is not None:
        await validate_bindings(
            db, tenant_id=tenant_id, kb_ids=payload.kb_ids, tool_ids=[]
        )
        await repo.replace_kbs(agent.id, payload.kb_ids)
    if payload.tool_ids is not None:
        await validate_bindings(
            db, tenant_id=tenant_id, kb_ids=[], tool_ids=payload.tool_ids
        )
        await repo.replace_tools(agent.id, payload.tool_ids)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            code=detail_from_integrity_error(exc, "agent_update_conflict")
        ) from exc
    await db.refresh(agent)
    return await agent_out(db, repo, agent)


async def publish_agent(
    db: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> AgentOut | None:
    repo = AgentRepository(db, tenant_id)
    agent = await repo.get_by_id(agent_id)
    if agent is None:
        return None
    agent.status = "active"
    await db.commit()
    await db.refresh(agent)
    return await agent_out(db, repo, agent)


async def archive_agent(db: AsyncSession, *, tenant_id: UUID, agent_id: UUID) -> bool:
    repo = AgentRepository(db, tenant_id)
    agent = await repo.update_by_id(agent_id, {"status": "archived"})
    if agent is None:
        return False
    await db.commit()
    return True


async def agent_out(db: AsyncSession, repo: AgentRepository, agent: Agent) -> AgentOut:
    return AgentOut(
        id=agent.id,
        tenant_id=agent.tenant_id,
        name=agent.name,
        type=agent.type,
        template_id=agent.template_id,
        persona=agent.persona,
        config=agent.config or {},
        model_id=agent.model_id,
        status=agent.status,
        created_by=agent.created_by,
        kb_ids=await repo.get_kb_ids(agent.id),
        tool_ids=await repo.get_tool_ids(agent.id),
    )


async def get_template(
    db: AsyncSession, template_id: UUID | None
) -> AgentTemplate | None:
    if template_id is None:
        return None
    return await db.get(AgentTemplate, template_id)


async def validate_model(db: AsyncSession, model_id: UUID) -> None:
    if await db.get(Model, model_id) is None:
        raise NotFoundError(code="model_not_found")


async def validate_bindings(
    db: AsyncSession, *, tenant_id: UUID, kb_ids: list[UUID], tool_ids: list[UUID]
) -> None:
    for kb_id in kb_ids:
        result = await db.execute(
            select(KnowledgeBase.id).where(
                KnowledgeBase.id == kb_id, KnowledgeBase.tenant_id == tenant_id
            )
        )
        if result.scalar_one_or_none() is None:
            raise NotFoundError(code="kb_not_found", detail={"id": str(kb_id)})

    for tool_id in tool_ids:
        result = await db.execute(
            select(Tool.id).where(Tool.id == tool_id, Tool.tenant_id == tenant_id)
        )
        if result.scalar_one_or_none() is None:
            raise NotFoundError(code="tool_not_found", detail={"id": str(tool_id)})
