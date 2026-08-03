import hashlib
import json
import secrets
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Agent,
    AppApiKey,
    ConversationIncident,
    Document,
    KnowledgeBase,
    Model,
    PublishedApp,
    PublishedAppVersion,
    Tool,
)
from app.repositories import AgentRepository
from app.schemas.publish import (
    AppApiKeyCreate,
    PublishedAppCreate,
    PublishedAppVersionCreate,
    PublishPrecheckOut,
)


async def create_published_app(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    payload: PublishedAppCreate,
) -> PublishedApp:
    agent = await db.get(Agent, payload.agent_id)
    if agent is None or agent.tenant_id != tenant_id or agent.status == "archived":
        raise ValueError("agent_not_found")
    if agent.status != "active":
        raise ValueError("agent_not_publishable")

    precheck = await run_publish_precheck(db, tenant_id=tenant_id, agent_id=agent.id)
    if precheck.status == "blocked":
        raise ValueError("publish_precheck_blocked")

    app = PublishedApp(
        tenant_id=tenant_id,
        agent_id=agent.id,
        name=payload.name or agent.name,
        status="published",
        publish_type=payload.publish_type,
        config=payload.config,
        created_by=user_id,
    )
    db.add(app)
    await db.flush()
    version = await create_published_app_version_record(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        app=app,
        agent=agent,
        title="v1",
        release_note=None,
        precheck=precheck,
        activate=True,
    )
    app.active_version_id = version.id
    await db.commit()
    await db.refresh(app)
    return app


async def list_published_apps(
    db: AsyncSession, *, tenant_id: UUID
) -> list[PublishedApp]:
    result = await db.execute(
        select(PublishedApp)
        .where(PublishedApp.tenant_id == tenant_id)
        .order_by(PublishedApp.created_at.desc())
    )
    return list(result.scalars().all())


async def published_app_out_data(db: AsyncSession, app: PublishedApp) -> dict:
    active_version_no = None
    if app.active_version_id is not None:
        version = await db.get(PublishedAppVersion, app.active_version_id)
        if version is not None:
            active_version_no = version.version_no
    return {
        "id": app.id,
        "tenant_id": app.tenant_id,
        "agent_id": app.agent_id,
        "name": app.name,
        "status": app.status,
        "publish_type": app.publish_type,
        "config": app.config,
        "created_by": app.created_by,
        "active_version_id": app.active_version_id,
        "active_version_no": active_version_no,
        "created_at": app.created_at,
        "updated_at": app.updated_at,
    }


async def get_published_app(
    db: AsyncSession, *, tenant_id: UUID, app_id: UUID
) -> PublishedApp | None:
    result = await db.execute(
        select(PublishedApp).where(
            PublishedApp.id == app_id, PublishedApp.tenant_id == tenant_id
        )
    )
    return result.scalar_one_or_none()


async def run_publish_precheck(
    db: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> PublishPrecheckOut:
    checks: list[dict] = []
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.tenant_id != tenant_id:
        checks.append(check("agent_active", "blocked", "block", "智能体不存在"))
        return PublishPrecheckOut(status="blocked", checks=checks)
    checks.append(
        check(
            "agent_active",
            "passed" if agent.status == "active" else "blocked",
            "block",
            "智能体已启用" if agent.status == "active" else "智能体未启用",
        )
    )
    model = await db.get(Model, agent.model_id) if agent.model_id else None
    model_ready = is_model_ready(model)
    checks.append(
        check(
            "model_config",
            "passed" if model_ready else "blocked",
            "block",
            f"模型已启用：{model.name}" if model_ready else "模型未配置或不可用",
        )
    )
    repo = AgentRepository(db, tenant_id)
    kb_ids = await repo.get_kb_ids(agent_id)
    tool_ids = await repo.get_tool_ids(agent_id)
    for kb_id in kb_ids:
        kb = await db.get(KnowledgeBase, kb_id)
        if kb is None or kb.tenant_id != tenant_id or kb.status != "active":
            checks.append(
                check("kb_status", "warning", "warning", f"知识库不可用：{kb_id}")
            )
            continue
        done_count = await scalar_count(
            db,
            select(func.count(Document.id)).where(
                Document.tenant_id == tenant_id,
                Document.kb_id == kb_id,
                Document.version_status == "active",
                Document.parse_status == "done",
            ),
        )
        checks.append(
            check(
                "kb_documents",
                "passed" if done_count > 0 else "warning",
                "warning",
                f"知识库 {kb.name} 可用文档 {done_count} 个",
            )
        )
    for tool_id in tool_ids:
        tool = await db.get(Tool, tool_id)
        checks.append(
            check(
                "tool_status",
                "passed"
                if tool is not None and tool.status == "active"
                else "warning",
                "warning",
                f"工具 {tool.name if tool else tool_id} 状态 {tool.status if tool else 'missing'}",
            )
        )
    high_incidents = await scalar_count(
        db,
        select(func.count(ConversationIncident.id)).where(
            ConversationIncident.tenant_id == tenant_id,
            ConversationIncident.agent_id == agent_id,
            ConversationIncident.status == "open",
            ConversationIncident.severity == "high",
        ),
    )
    checks.append(
        check(
            "incidents",
            "warning" if high_incidents else "passed",
            "warning",
            f"open 高危问题 {high_incidents} 个",
        )
    )
    security_incidents = await scalar_count(
        db,
        select(func.count(ConversationIncident.id)).where(
            ConversationIncident.tenant_id == tenant_id,
            ConversationIncident.agent_id == agent_id,
            ConversationIncident.status == "open",
            ConversationIncident.incident_type == "security_eval_failed",
        ),
    )
    checks.append(
        check(
            "security_eval",
            "warning" if security_incidents else "passed",
            "warning",
            f"open 安全评测失败 {security_incidents} 个",
        )
    )
    status = "blocked" if any(item["status"] == "blocked" for item in checks) else (
        "warning" if any(item["status"] == "warning" for item in checks) else "passed"
    )
    output = PublishPrecheckOut(status=status, checks=checks)
    confirmation = await build_publish_confirmation(db, tenant_id=tenant_id, agent=agent)
    output_dict = output.model_dump(mode="json")
    output_dict["confirmation"] = confirmation
    return PublishPrecheckOut.model_validate(output_dict)


async def create_published_app_version(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    app_id: UUID,
    payload: PublishedAppVersionCreate,
) -> PublishedAppVersion | None:
    app = await get_published_app(db, tenant_id=tenant_id, app_id=app_id)
    if app is None:
        return None
    agent = await db.get(Agent, app.agent_id)
    if agent is None or agent.tenant_id != tenant_id:
        raise ValueError("agent_not_found")
    precheck = await run_publish_precheck(db, tenant_id=tenant_id, agent_id=agent.id)
    if precheck.status == "blocked" and not payload.force:
        raise ValueError("publish_precheck_blocked")
    version = await create_published_app_version_record(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        app=app,
        agent=agent,
        title=payload.title,
        release_note=payload.release_note,
        precheck=precheck,
        activate=payload.activate,
    )
    await db.commit()
    await db.refresh(version)
    return version


async def create_published_app_version_record(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    app: PublishedApp,
    agent: Agent,
    title: str | None,
    release_note: str | None,
    precheck: PublishPrecheckOut,
    activate: bool,
) -> PublishedAppVersion:
    version_no = await next_version_no(db, tenant_id=tenant_id, app_id=app.id)
    if activate:
        await deactivate_app_versions(db, tenant_id=tenant_id, app_id=app.id)
    version = PublishedAppVersion(
        tenant_id=tenant_id,
        app_id=app.id,
        agent_id=agent.id,
        version_no=version_no,
        status="active" if activate else "inactive",
        title=title or f"v{version_no}",
        release_note=release_note,
        snapshot=await build_publish_snapshot(db, tenant_id=tenant_id, agent=agent),
        precheck_result=precheck.model_dump(mode="json"),
        created_by=user_id,
        activated_at=datetime.now(timezone.utc) if activate else None,
    )
    db.add(version)
    await db.flush()
    if activate:
        app.active_version_id = version.id
    return version


async def list_published_app_versions(
    db: AsyncSession, *, tenant_id: UUID, app_id: UUID
) -> list[PublishedAppVersion] | None:
    if await get_published_app(db, tenant_id=tenant_id, app_id=app_id) is None:
        return None
    result = await db.execute(
        select(PublishedAppVersion)
        .where(
            PublishedAppVersion.tenant_id == tenant_id,
            PublishedAppVersion.app_id == app_id,
        )
        .order_by(PublishedAppVersion.version_no.desc())
    )
    return list(result.scalars().all())


async def activate_published_app_version(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    app_id: UUID,
    version_id: UUID,
) -> PublishedAppVersion | None:
    app = await get_published_app(db, tenant_id=tenant_id, app_id=app_id)
    version = await db.get(PublishedAppVersion, version_id)
    if (
        app is None
        or version is None
        or version.tenant_id != tenant_id
        or version.app_id != app_id
    ):
        return None
    await deactivate_app_versions(db, tenant_id=tenant_id, app_id=app_id)
    version.status = "active"
    version.activated_at = datetime.now(timezone.utc)
    app.active_version_id = version.id
    await db.commit()
    await db.refresh(version)
    return version


async def deactivate_app_versions(
    db: AsyncSession, *, tenant_id: UUID, app_id: UUID
) -> None:
    await db.execute(
        update(PublishedAppVersion)
        .where(
            PublishedAppVersion.tenant_id == tenant_id,
            PublishedAppVersion.app_id == app_id,
            PublishedAppVersion.status == "active",
        )
        .values(status="inactive")
    )


async def next_version_no(db: AsyncSession, *, tenant_id: UUID, app_id: UUID) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(PublishedAppVersion.version_no), 0)).where(
            PublishedAppVersion.tenant_id == tenant_id,
            PublishedAppVersion.app_id == app_id,
        )
    )
    return int(result.scalar_one() or 0) + 1


async def build_publish_snapshot(
    db: AsyncSession, *, tenant_id: UUID, agent: Agent
) -> dict:
    repo = AgentRepository(db, tenant_id)
    kb_ids = await repo.get_kb_ids(agent.id)
    tool_ids = await repo.get_tool_ids(agent.id)
    model = await db.get(Model, agent.model_id) if agent.model_id else None
    return {
        "schema_version": "m5_v1",
        "created_from": "agent",
        "agent": {
            "id": str(agent.id),
            "name": agent.name,
            "type": agent.type,
            "persona": agent.persona,
            "config": agent.config or {},
            "model_id": str(agent.model_id) if agent.model_id else None,
        },
        "kb_ids": [str(kb_id) for kb_id in kb_ids],
        "tool_ids": [str(tool_id) for tool_id in tool_ids],
        "model": {
            "id": str(model.id) if model else None,
            "name": model.name if model else None,
        },
    }


async def agent_configuration_hash(
    db: AsyncSession, *, tenant_id: UUID, agent: Agent
) -> str:
    snapshot = await build_publish_snapshot(db, tenant_id=tenant_id, agent=agent)
    payload = {
        "agent": snapshot["agent"],
        "kb_ids": snapshot["kb_ids"],
        "tool_ids": snapshot["tool_ids"],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def build_publish_confirmation(
    db: AsyncSession, *, tenant_id: UUID, agent: Agent
) -> dict:
    return {
        "confirmation_id": str(uuid4()),
        "agent_id": str(agent.id),
        "config_version": agent.updated_at.isoformat() if getattr(agent, "updated_at", None) else None,
        "configuration_hash": await agent_configuration_hash(db, tenant_id=tenant_id, agent=agent),
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
    }


async def validate_publish_confirmation(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    agent: Agent,
    expected_configuration_hash: str | None,
) -> None:
    if not expected_configuration_hash:
        raise ValueError("publish_confirmation_version_required")
    current_hash = await agent_configuration_hash(db, tenant_id=tenant_id, agent=agent)
    if current_hash != expected_configuration_hash:
        raise ValueError("publish_confirmation_stale")


async def scalar_count(db: AsyncSession, stmt) -> int:
    result = await db.execute(stmt)
    return int(result.scalar_one() or 0)


def check(name: str, status: str, level: str, message: str) -> dict:
    return {"check": name, "status": status, "level": level, "message": message}


def is_model_ready(model: Model | None) -> bool:
    return model is not None and model.is_active is not False


async def unpublish_app(
    db: AsyncSession, *, tenant_id: UUID, app_id: UUID
) -> PublishedApp | None:
    app = await get_published_app(db, tenant_id=tenant_id, app_id=app_id)
    if app is None:
        return None
    app.status = "unpublished"
    await db.commit()
    await db.refresh(app)
    return app


async def create_app_api_key(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    app_id: UUID,
    payload: AppApiKeyCreate,
) -> tuple[AppApiKey, str]:
    app = await get_published_app(db, tenant_id=tenant_id, app_id=app_id)
    if app is None:
        raise ValueError("published_app_not_found")
    if app.status != "published":
        raise ValueError("published_app_not_active")

    raw_key = generate_api_key()
    key = AppApiKey(
        tenant_id=tenant_id,
        app_id=app.id,
        name=payload.name,
        key_hash=hash_api_key(raw_key),
        key_prefix=mask_api_key(raw_key),
        scopes=payload.scopes,
        config=payload.config,
        status="active",
        expires_at=payload.expires_at,
        created_by=user_id,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return key, raw_key


async def list_app_api_keys(
    db: AsyncSession, *, tenant_id: UUID, app_id: UUID
) -> list[AppApiKey] | None:
    if await get_published_app(db, tenant_id=tenant_id, app_id=app_id) is None:
        return None
    result = await db.execute(
        select(AppApiKey)
        .where(AppApiKey.tenant_id == tenant_id, AppApiKey.app_id == app_id)
        .order_by(AppApiKey.created_at.desc())
    )
    return list(result.scalars().all())


async def set_app_api_key_status(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    app_id: UUID,
    key_id: UUID,
    status: str,
) -> AppApiKey | None:
    result = await db.execute(
        select(AppApiKey).where(
            AppApiKey.id == key_id,
            AppApiKey.tenant_id == tenant_id,
            AppApiKey.app_id == app_id,
        )
    )
    key = result.scalar_one_or_none()
    if key is None:
        return None
    key.status = status
    await db.commit()
    await db.refresh(key)
    return key


def generate_api_key() -> str:
    return f"sk-{secrets.token_urlsafe(32)}"


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def mask_api_key(api_key: str) -> str:
    return f"{api_key[:10]}****"
