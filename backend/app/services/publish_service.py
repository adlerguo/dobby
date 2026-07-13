import hashlib
import secrets
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, AppApiKey, PublishedApp
from app.schemas.publish import AppApiKeyCreate, PublishedAppCreate


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
    await db.commit()
    await db.refresh(app)
    return app


async def list_published_apps(db: AsyncSession, *, tenant_id: UUID) -> list[PublishedApp]:
    result = await db.execute(
        select(PublishedApp)
        .where(PublishedApp.tenant_id == tenant_id)
        .order_by(PublishedApp.created_at.desc())
    )
    return list(result.scalars().all())


async def get_published_app(db: AsyncSession, *, tenant_id: UUID, app_id: UUID) -> PublishedApp | None:
    result = await db.execute(
        select(PublishedApp).where(PublishedApp.id == app_id, PublishedApp.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def unpublish_app(db: AsyncSession, *, tenant_id: UUID, app_id: UUID) -> PublishedApp | None:
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
        status="active",
        expires_at=payload.expires_at,
        created_by=user_id,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return key, raw_key


async def list_app_api_keys(db: AsyncSession, *, tenant_id: UUID, app_id: UUID) -> list[AppApiKey] | None:
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
