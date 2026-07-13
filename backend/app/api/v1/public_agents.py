from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_key_auth import AppApiKeyContext, get_app_api_key_context
from app.core.database import get_db
from app.models import AppApiKey, UsageRecord
from app.orchestrator import dispatch_single_agent
from app.schemas.agent_run import AgentRunIn
from app.schemas.public_chat import PublicChatIn, PublicChatOut

router = APIRouter(prefix="/public/apps", tags=["public-apps"])


@router.post("/{app_id}/chat", response_model=PublicChatOut, summary="Invoke published agent with API key")
async def public_app_chat_api(
    app_id: UUID,
    payload: PublicChatIn,
    auth: AppApiKeyContext = Depends(get_app_api_key_context),
    db: AsyncSession = Depends(get_db),
) -> PublicChatOut:
    if payload.stream:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="stream_not_supported")

    try:
        result = await dispatch_single_agent(
            db,
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            agent_id=auth.agent_id,
            payload=AgentRunIn(
                query=payload.query,
                conversation_id=payload.conversation_id,
                max_tokens=payload.max_tokens,
                history_limit=payload.history_limit,
                top_k=payload.top_k,
                score_threshold=payload.score_threshold,
                match_type=payload.match_type,
                max_tool_rounds=0,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="app_unavailable")

    await mark_key_used_and_record_usage(db, auth=auth, usage=result.usage)
    return PublicChatOut(
        answer=result.answer,
        citations=result.citations,
        conversation_id=result.conversation_id,
        usage=result.usage,
    )


async def mark_key_used_and_record_usage(
    db: AsyncSession,
    *,
    auth: AppApiKeyContext,
    usage: dict,
) -> None:
    key = await db.get(AppApiKey, auth.key_id)
    if key is not None:
        key.last_used_at = datetime.now(UTC)

    db.add(
        UsageRecord(
            tenant_id=auth.tenant_id,
            agent_id=auth.agent_id,
            user_id=auth.user_id,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            latency_ms=None,
            cost=None,
            cache_hit=False,
        )
    )
    await db.commit()
