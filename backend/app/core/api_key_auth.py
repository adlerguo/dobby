from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Agent, AppApiKey, PublishedApp
from app.services.publish_service import hash_api_key

api_key_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AppApiKeyContext:
    tenant_id: UUID
    app_id: UUID
    agent_id: UUID
    key_id: UUID
    user_id: UUID
    config: dict


async def get_app_api_key_context(
    app_id: UUID,
    credentials: HTTPAuthorizationCredentials | None = Depends(api_key_bearer),
    db: AsyncSession = Depends(get_db),
) -> AppApiKeyContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise invalid_credentials()

    key_hash = hash_api_key(credentials.credentials)
    result = await db.execute(select(AppApiKey).where(AppApiKey.key_hash == key_hash))
    key = result.scalar_one_or_none()
    if key is None or key.status != "active" or is_expired(key):
        raise invalid_credentials()
    if key.app_id != app_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="app_forbidden"
        )

    app = await db.get(PublishedApp, key.app_id)
    if app is None or app.tenant_id != key.tenant_id or app.status != "published":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="app_unavailable"
        )

    agent = await db.get(Agent, app.agent_id)
    if agent is None or agent.tenant_id != app.tenant_id or agent.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="app_unavailable"
        )

    user_id = key.created_by or app.created_by
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="app_unavailable"
        )

    return AppApiKeyContext(
        tenant_id=key.tenant_id,
        app_id=app.id,
        agent_id=app.agent_id,
        key_id=key.id,
        user_id=user_id,
        config=key.config or {},
    )


def is_expired(key: AppApiKey) -> bool:
    if key.expires_at is None:
        return False
    expires_at = key.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)


def invalid_credentials() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid_credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
