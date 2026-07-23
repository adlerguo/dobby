import json
import time
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse, StreamingResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.chat import PRE_STREAM_ERROR_STATUS
from app.api.v1.public_agents import mark_key_used_and_record_usage
from app.core.api_key_auth import AppApiKeyContext, get_app_api_key_context
from app.core.database import SessionLocal, get_db
from app.core.public_limits import enforce_public_key_limits, record_public_key_usage
from app.core.redis import get_redis
from app.orchestrator import (
    dispatch_single_agent,
    stream_agent_events as run_stream_agent_events,
)
from app.schemas.agent_run import AgentRunIn
from app.schemas.openai_compat import ChatCompletionMessage, ChatCompletionRequest

router = APIRouter(prefix="/public/apps/{app_id}/openai/v1", tags=["openai-compat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}
PRE_STREAM_ERROR_PREFIX = "__openai_pre_stream_error__:"


@router.post(
    "/chat/completions",
    response_model=None,
    summary="OpenAI compatible public app chat completions",
    description=(
        "OpenAI SDK base_url: https://<host>/api/v1/public/apps/<app_id>/openai/v1. "
        "Use the app API key as api_key. The model field is echoed only; the bound agent chooses the actual model."
    ),
)
async def openai_chat_completions_api(
    app_id: UUID,
    payload: ChatCompletionRequest,
    auth: AppApiKeyContext = Depends(get_app_api_key_context),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict | JSONResponse | StreamingResponse:
    """
    OpenAI SDK:
    base_url = https://<host>/api/v1/public/apps/<app_id>/openai/v1
    api_key = app API Key
    model = any placeholder string; the bound agent configuration selects the actual model.
    """
    query = fold_messages_to_query(payload.messages)
    if query is None:
        return openai_error(
            status.HTTP_400_BAD_REQUEST,
            "At least one user message is required.",
            "invalid_request_error",
            "no_user_message",
        )

    await enforce_public_key_limits(redis, auth)
    agent_payload = AgentRunIn(
        query=query, max_tokens=clamp_max_tokens(payload.max_tokens), max_tool_rounds=0
    )
    if payload.stream:
        events = stream_openai_chat_events(
            auth=auth,
            payload=agent_payload,
            redis=redis,
            model=payload.model,
            include_usage=bool(
                payload.stream_options and payload.stream_options.include_usage
            ),
        )
        first_event = await anext(events, None)
        if first_event is None:
            return StreamingResponse(
                iter(()), media_type="text/event-stream", headers=SSE_HEADERS
            )

        error_detail = pre_stream_error_detail(first_event)
        if error_detail is not None:
            await events.aclose()
            return openai_error(
                PRE_STREAM_ERROR_STATUS[error_detail],
                error_detail,
                "server_error",
                error_detail,
            )

        return StreamingResponse(
            prepend_openai_event(first_event, events),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    try:
        result = await dispatch_single_agent(
            db,
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            agent_id=auth.agent_id,
            payload=agent_payload,
        )
    except ValueError as exc:
        detail = str(exc)
        error_status = (
            status.HTTP_409_CONFLICT
            if detail == "no_active_model_channel"
            else status.HTTP_400_BAD_REQUEST
        )
        error_type = (
            "server_error"
            if detail == "no_active_model_channel"
            else "invalid_request_error"
        )
        return openai_error(error_status, detail, error_type, detail)

    if result is None:
        return openai_error(
            status.HTTP_403_FORBIDDEN,
            "app_unavailable",
            "server_error",
            "app_unavailable",
        )

    usage = normalize_usage(result.usage)
    await mark_key_used_and_record_usage(db, auth=auth, usage=usage)
    await record_public_key_usage(redis, auth, usage)
    response = openai_completion_response(
        model=payload.model, answer=result.answer, usage=usage
    )
    if result.citations:
        response["x_citations"] = [
            citation.model_dump(mode="json") for citation in result.citations
        ]
    return response


def fold_messages_to_query(messages: list[ChatCompletionMessage]) -> str | None:
    last_user_index = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if messages[index].role == "user"
        ),
        None,
    )
    if last_user_index is None:
        return None

    current_question = messages[last_user_index].content
    history_lines: list[str] = []
    for message in messages[:last_user_index]:
        if message.role == "user":
            history_lines.append(f"用户: {message.content}")
        elif message.role == "assistant":
            history_lines.append(f"助手: {message.content}")
    if not history_lines:
        return current_question
    history = "\n".join(history_lines)
    return f"历史:\n{history}\n\n当前问题:\n{current_question}"


def clamp_max_tokens(max_tokens: int | None) -> int:
    if max_tokens is None:
        return 3500
    return max(256, min(int(max_tokens), 32000))


def normalize_usage(usage: dict[str, Any] | None) -> dict[str, int]:
    usage = usage or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def openai_completion_response(
    *, model: str, answer: str, usage: dict[str, int]
) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
    }


def openai_error(
    status_code: int, message: str, error_type: str, code: str
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": message, "type": error_type, "code": code}},
    )


def pre_stream_error_detail(frame: str) -> str | None:
    if not frame.startswith(PRE_STREAM_ERROR_PREFIX):
        return None
    detail = frame.removeprefix(PRE_STREAM_ERROR_PREFIX)
    return detail if detail in PRE_STREAM_ERROR_STATUS else None


def internal_error_detail(event: dict[str, Any]) -> str | None:
    if event.get("event") != "error":
        return None
    data = event.get("data") or {}
    code = data.get("code")
    if isinstance(code, str):
        return code
    detail = data.get("detail")
    return detail if isinstance(detail, str) else None


async def stream_openai_chat_events(
    *,
    auth: AppApiKeyContext,
    payload: AgentRunIn,
    redis: Redis,
    model: str,
    include_usage: bool,
) -> AsyncGenerator[str, None]:
    cmpl_id = f"chatcmpl-{uuid4().hex}"
    usage: dict[str, int] = normalize_usage({})
    started = False
    async with SessionLocal() as db:
        try:
            events = run_stream_agent_events(
                db,
                tenant_id=auth.tenant_id,
                user_id=auth.user_id,
                agent_id=auth.agent_id,
                payload=payload,
            )
            first_event = await anext(events, None)
            if first_event is None:
                yield openai_chunk({"role": "assistant"}, None, model, cmpl_id)
                yield openai_chunk({}, "stop", model, cmpl_id)
                yield "data: [DONE]\n\n"
                return

            first_error = internal_error_detail(first_event)
            if first_error in PRE_STREAM_ERROR_STATUS:
                yield f"{PRE_STREAM_ERROR_PREFIX}{first_error}"
                return

            yield openai_chunk({"role": "assistant"}, None, model, cmpl_id)
            started = True
            async for frame in stream_internal_events(
                first_event=first_event,
                events=events,
                model=model,
                cmpl_id=cmpl_id,
                include_usage=include_usage,
                usage_ref={"usage": usage},
            ):
                if frame["type"] == "usage":
                    usage = frame["usage"]
                else:
                    yield frame["data"]
        except ValueError as exc:
            detail = str(exc)
            if not started and detail in PRE_STREAM_ERROR_STATUS:
                yield f"{PRE_STREAM_ERROR_PREFIX}{detail}"
            else:
                yield openai_error_frame({"code": detail, "detail": detail})
                yield "data: [DONE]\n\n"
            return
        finally:
            await mark_key_used_and_record_usage(db, auth=auth, usage=usage)
            await record_public_key_usage(redis, auth, usage)


async def stream_internal_events(
    *,
    first_event: dict[str, Any],
    events: AsyncGenerator[dict[str, Any], None],
    model: str,
    cmpl_id: str,
    include_usage: bool,
    usage_ref: dict[str, dict[str, int]],
) -> AsyncGenerator[dict[str, Any], None]:
    for event in [first_event]:
        async for frame in openai_frames_for_internal_event(
            event=event,
            model=model,
            cmpl_id=cmpl_id,
            include_usage=include_usage,
            usage_ref=usage_ref,
        ):
            yield frame
    async for event in events:
        async for frame in openai_frames_for_internal_event(
            event=event,
            model=model,
            cmpl_id=cmpl_id,
            include_usage=include_usage,
            usage_ref=usage_ref,
        ):
            yield frame


async def openai_frames_for_internal_event(
    *,
    event: dict[str, Any],
    model: str,
    cmpl_id: str,
    include_usage: bool,
    usage_ref: dict[str, dict[str, int]],
) -> AsyncGenerator[dict[str, Any], None]:
    event_type = event["event"]
    data = event["data"]
    if event_type == "delta":
        yield {
            "type": "data",
            "data": openai_chunk(
                {"content": data.get("text", "")}, None, model, cmpl_id
            ),
        }
    elif event_type == "done":
        usage = normalize_usage(data.get("usage"))
        usage_ref["usage"] = usage
        yield {"type": "usage", "usage": usage}
        yield {"type": "data", "data": openai_chunk({}, "stop", model, cmpl_id)}
        if include_usage:
            yield {
                "type": "data",
                "data": openai_usage_chunk(model=model, cmpl_id=cmpl_id, usage=usage),
            }
        yield {"type": "data", "data": "data: [DONE]\n\n"}
    elif event_type == "error":
        yield {"type": "data", "data": openai_error_frame(data)}
        yield {"type": "data", "data": "data: [DONE]\n\n"}


def openai_chunk(
    delta: dict[str, Any], finish_reason: str | None, model: str, cmpl_id: str
) -> str:
    payload = {
        "id": cmpl_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def openai_usage_chunk(*, model: str, cmpl_id: str, usage: dict[str, int]) -> str:
    payload = {
        "id": cmpl_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [],
        "usage": usage,
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def openai_error_frame(data: dict[str, Any]) -> str:
    code = data.get("code") or data.get("detail") or "server_error"
    detail = data.get("detail") or code
    payload = {"error": {"message": detail, "type": "server_error", "code": code}}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def prepend_openai_event(
    first_event: str, events: AsyncGenerator[str, None]
) -> AsyncGenerator[str, None]:
    yield first_event
    async for event in events:
        yield event
