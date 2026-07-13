from collections import defaultdict
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, KnowledgeBase, Model, Tool, Workspace, WorkspaceResource
from app.schemas import WorkspaceCreate, WorkspaceOut, WorkspaceResourceIn, WorkspaceResourceOut, WorkspaceUpdate
from app.services.validation import detail_from_integrity_error, ensure_tenant_name_available


async def list_workspaces(db: AsyncSession, *, tenant_id: UUID) -> list[WorkspaceOut]:
    result = await db.execute(
        select(Workspace).where(Workspace.tenant_id == tenant_id).order_by(Workspace.created_at.desc())
    )
    return [await workspace_out(db, workspace) for workspace in result.scalars().all()]


async def get_workspace(db: AsyncSession, *, tenant_id: UUID, workspace_id: UUID) -> WorkspaceOut | None:
    workspace = await load_workspace(db, tenant_id=tenant_id, workspace_id=workspace_id)
    if workspace is None:
        return None
    return await workspace_out(db, workspace)


async def create_workspace(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    payload: WorkspaceCreate,
) -> WorkspaceOut:
    await ensure_tenant_name_available(
        db,
        model=Workspace,
        tenant_id=tenant_id,
        name=payload.name,
        detail="workspace_name_exists",
        ignore_archived=False,
    )
    workspace = Workspace(
        tenant_id=tenant_id,
        name=payload.name,
        layout=payload.layout,
        created_by=user_id,
    )
    try:
        db.add(workspace)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError(detail_from_integrity_error(exc, "workspace_create_conflict")) from exc
    await db.refresh(workspace)
    return await workspace_out(db, workspace)


async def update_workspace(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    payload: WorkspaceUpdate,
) -> WorkspaceOut | None:
    workspace = await load_workspace(db, tenant_id=tenant_id, workspace_id=workspace_id)
    if workspace is None:
        return None

    values = payload.model_dump(exclude_unset=True)
    if payload.name is not None:
        await ensure_tenant_name_available(
            db,
            model=Workspace,
            tenant_id=tenant_id,
            name=payload.name,
            detail="workspace_name_exists",
            exclude_id=workspace_id,
            ignore_archived=False,
        )
    for key, value in values.items():
        setattr(workspace, key, value)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError(detail_from_integrity_error(exc, "workspace_update_conflict")) from exc
    await db.refresh(workspace)
    return await workspace_out(db, workspace)


async def attach_workspace_resource(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    payload: WorkspaceResourceIn,
) -> WorkspaceOut | None:
    workspace = await load_workspace(db, tenant_id=tenant_id, workspace_id=workspace_id)
    if workspace is None:
        return None
    await validate_workspace_resource(db, tenant_id=tenant_id, payload=payload)

    existing = await load_resource(
        db,
        workspace_id=workspace_id,
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
    )
    if existing is None:
        db.add(
            WorkspaceResource(
                workspace_id=workspace_id,
                resource_type=payload.resource_type,
                resource_id=payload.resource_id,
            )
        )
    await db.commit()
    await db.refresh(workspace)
    return await workspace_out(db, workspace)


async def detach_workspace_resource(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    payload: WorkspaceResourceIn,
) -> bool:
    workspace = await load_workspace(db, tenant_id=tenant_id, workspace_id=workspace_id)
    if workspace is None:
        return False
    result = await db.execute(
        delete(WorkspaceResource).where(
            WorkspaceResource.workspace_id == workspace_id,
            WorkspaceResource.resource_type == payload.resource_type,
            WorkspaceResource.resource_id == payload.resource_id,
        )
    )
    await db.commit()
    return bool(result.rowcount)


async def get_workspace_resource_ids(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID | None,
) -> dict[str, list[UUID]]:
    if workspace_id is None:
        return {"kb": [], "agent": [], "tool": [], "model": []}
    workspace = await load_workspace(db, tenant_id=tenant_id, workspace_id=workspace_id)
    if workspace is None:
        raise ValueError("workspace_not_found")

    result = await db.execute(
        select(WorkspaceResource).where(WorkspaceResource.workspace_id == workspace_id).order_by(WorkspaceResource.id)
    )
    grouped: dict[str, list[UUID]] = {"kb": [], "agent": [], "tool": [], "model": []}
    for resource in result.scalars().all():
        if resource.resource_type in grouped and resource.resource_id is not None:
            grouped[resource.resource_type].append(resource.resource_id)
    return grouped


async def workspace_out(db: AsyncSession, workspace: Workspace) -> WorkspaceOut:
    resources = await load_resources(db, workspace_id=workspace.id)
    return WorkspaceOut(
        id=workspace.id,
        tenant_id=workspace.tenant_id,
        name=workspace.name,
        layout=workspace.layout or {},
        created_by=workspace.created_by,
        created_at=workspace.created_at,
        resources=await resource_outs(db, workspace.tenant_id, resources),
    )


async def load_workspace(db: AsyncSession, *, tenant_id: UUID, workspace_id: UUID) -> Workspace | None:
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id, Workspace.tenant_id == tenant_id))
    return result.scalar_one_or_none()


async def load_resources(db: AsyncSession, *, workspace_id: UUID) -> list[WorkspaceResource]:
    result = await db.execute(
        select(WorkspaceResource).where(WorkspaceResource.workspace_id == workspace_id).order_by(WorkspaceResource.id)
    )
    return list(result.scalars().all())


async def load_resource(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    resource_type: str,
    resource_id: UUID,
) -> WorkspaceResource | None:
    result = await db.execute(
        select(WorkspaceResource).where(
            WorkspaceResource.workspace_id == workspace_id,
            WorkspaceResource.resource_type == resource_type,
            WorkspaceResource.resource_id == resource_id,
        )
    )
    return result.scalar_one_or_none()


async def validate_workspace_resource(db: AsyncSession, *, tenant_id: UUID, payload: WorkspaceResourceIn) -> None:
    if payload.resource_type == "kb":
        result = await db.execute(
            select(KnowledgeBase.id).where(
                KnowledgeBase.id == payload.resource_id,
                KnowledgeBase.tenant_id == tenant_id,
                KnowledgeBase.status != "archived",
            )
        )
        if result.scalar_one_or_none() is None:
            raise ValueError("kb_not_found")
        return

    if payload.resource_type == "agent":
        result = await db.execute(
            select(Agent.id).where(
                Agent.id == payload.resource_id,
                Agent.tenant_id == tenant_id,
                Agent.status != "archived",
            )
        )
        if result.scalar_one_or_none() is None:
            raise ValueError("agent_not_found")
        return

    if payload.resource_type == "tool":
        result = await db.execute(
            select(Tool.id).where(
                Tool.id == payload.resource_id,
                Tool.tenant_id == tenant_id,
                Tool.status != "archived",
            )
        )
        if result.scalar_one_or_none() is None:
            raise ValueError("tool_not_found")
        return

    if payload.resource_type == "model":
        result = await db.execute(select(Model.id).where(Model.id == payload.resource_id))
        if result.scalar_one_or_none() is None:
            raise ValueError("model_not_found")
        return

    raise ValueError("resource_type_invalid")


async def resource_outs(
    db: AsyncSession,
    tenant_id: UUID,
    resources: list[WorkspaceResource],
) -> list[WorkspaceResourceOut]:
    names = await load_resource_names(db, tenant_id=tenant_id, resources=resources)
    return [
        WorkspaceResourceOut(
            id=resource.id,
            workspace_id=resource.workspace_id,
            resource_type=resource.resource_type,
            resource_id=resource.resource_id,
            resource_name=names.get((resource.resource_type, resource.resource_id), {}).get("name"),
            resource_status=names.get((resource.resource_type, resource.resource_id), {}).get("status"),
        )
        for resource in resources
    ]


async def load_resource_names(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    resources: list[WorkspaceResource],
) -> dict[tuple[str | None, UUID | None], dict[str, str | None]]:
    grouped: dict[str, list[UUID]] = defaultdict(list)
    for resource in resources:
        if resource.resource_type is not None and resource.resource_id is not None:
            grouped[resource.resource_type].append(resource.resource_id)

    names: dict[tuple[str | None, UUID | None], dict[str, str | None]] = {}
    if grouped.get("kb"):
        result = await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.tenant_id == tenant_id, KnowledgeBase.id.in_(grouped["kb"]))
        )
        for kb in result.scalars().all():
            names[("kb", kb.id)] = {"name": kb.name, "status": kb.status}
    if grouped.get("agent"):
        result = await db.execute(select(Agent).where(Agent.tenant_id == tenant_id, Agent.id.in_(grouped["agent"])))
        for agent in result.scalars().all():
            names[("agent", agent.id)] = {"name": agent.name, "status": agent.status}
    if grouped.get("tool"):
        result = await db.execute(select(Tool).where(Tool.tenant_id == tenant_id, Tool.id.in_(grouped["tool"])))
        for tool in result.scalars().all():
            names[("tool", tool.id)] = {"name": tool.name, "status": tool.status}
    if grouped.get("model"):
        result = await db.execute(select(Model).where(Model.id.in_(grouped["model"])))
        for model in result.scalars().all():
            names[("model", model.id)] = {"name": model.name, "status": model.type}
    return names
