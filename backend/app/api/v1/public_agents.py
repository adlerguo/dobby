from collections.abc import AsyncGenerator
from datetime import UTC, datetime
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.chat import (
    PRE_STREAM_ERROR_STATUS,
    prepend_event,
    sse_error_detail,
    sse_event,
)
from app.core.api_key_auth import AppApiKeyContext, get_app_api_key_context
from app.core.database import SessionLocal, get_db
from app.core.public_limits import enforce_public_key_limits, record_public_key_usage
from app.core.redis import get_redis
from app.models import AppApiKey, UsageRecord
from app.orchestrator import (
    dispatch_single_agent,
    stream_agent_events as run_stream_agent_events,
)
from app.schemas.agent_run import AgentRunIn
from app.schemas.public_chat import PublicChatIn, PublicChatOut

router = APIRouter(prefix="/public/apps", tags=["public-apps"])
logger = logging.getLogger(__name__)
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


@router.post(
    "/{app_id}/chat",
    response_model=PublicChatOut,
    summary="Invoke published agent with API key",
)
async def public_app_chat_api(
    app_id: UUID,
    payload: PublicChatIn,
    auth: AppApiKeyContext = Depends(get_app_api_key_context),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> PublicChatOut | StreamingResponse:
    if payload.stream:
        return await public_app_chat_stream_api(
            app_id=app_id, payload=payload, auth=auth, redis=redis
        )

    return await invoke_public_chat(db=db, redis=redis, auth=auth, payload=payload)


@router.post("/{app_id}/chat/stream", summary="Stream published agent with API key")
async def public_app_chat_stream_api(
    app_id: UUID,
    payload: PublicChatIn,
    auth: AppApiKeyContext = Depends(get_app_api_key_context),
    redis: Redis = Depends(get_redis),
) -> StreamingResponse:
    await enforce_public_key_limits(redis, auth)
    events = stream_public_chat_events(auth=auth, payload=payload, redis=redis)
    first_event = await anext(events, None)
    if first_event is None:
        return StreamingResponse(
            iter(()), media_type="text/event-stream", headers=SSE_HEADERS
        )

    error_detail = sse_error_detail(first_event)
    if error_detail in PRE_STREAM_ERROR_STATUS:
        await events.aclose()
        raise HTTPException(
            status_code=PRE_STREAM_ERROR_STATUS[error_detail], detail=error_detail
        )

    return StreamingResponse(
        prepend_event(first_event, events),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


async def invoke_public_chat(
    *,
    db: AsyncSession,
    redis: Redis,
    auth: AppApiKeyContext,
    payload: PublicChatIn,
) -> PublicChatOut:
    await enforce_public_key_limits(redis, auth)
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
                rerank_mode=payload.rerank_mode,
                max_tool_rounds=0,
                runtime_snapshot=auth.runtime_snapshot,
            ),
        )
    except ValueError as exc:
        if str(exc) == "no_active_model_channel":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="app_unavailable"
        )

    await mark_key_used_and_record_usage(db, auth=auth, usage=result.usage)
    await record_public_key_usage(redis, auth, result.usage)
    return PublicChatOut(
        answer=result.answer,
        citations=result.citations,
        conversation_id=result.conversation_id,
        usage=result.usage,
    )


async def stream_public_chat_events(
    *,
    auth: AppApiKeyContext,
    payload: PublicChatIn,
    redis: Redis,
) -> AsyncGenerator[str, None]:
    stream_metadata: dict[str, Any] = {"usage": {}, "conversation_id": None}
    async with SessionLocal() as db:
        try:
            async for event in run_stream_agent_events(
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
                    rerank_mode=payload.rerank_mode,
                    max_tool_rounds=0,
                    runtime_snapshot=auth.runtime_snapshot,
                ),
            ):
                if event["event"] == "done":
                    data = event["data"]
                    stream_metadata["usage"] = data.get("usage") or {}
                    stream_metadata["conversation_id"] = data.get("conversation_id")
                yield sse_event(event["event"], event["data"])
        except ValueError as exc:
            code = getattr(exc, "code", str(exc))
            detail = getattr(exc, "detail", str(exc))
            yield sse_event("error", {"code": code, "detail": detail})
            return
        finally:
            usage = stream_metadata["usage"]
            accounting_error: Exception | None = None
            try:
                await mark_key_used_and_record_usage(db, auth=auth, usage=usage)
            except Exception as exc:
                accounting_error = exc
            try:
                await record_public_key_usage(redis, auth, usage)
            except Exception as exc:
                accounting_error = accounting_error or exc
            if accounting_error is not None:
                logger.error(
                    "public_stream_usage_record_failed key_id=%s agent_id=%s",
                    auth.key_id,
                    auth.agent_id,
                    exc_info=(
                        type(accounting_error),
                        accounting_error,
                        accounting_error.__traceback__,
                    ),
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
