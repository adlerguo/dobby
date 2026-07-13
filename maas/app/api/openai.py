import json
import time
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_redis
from app.core.database import get_db
from app.models import models
from app.schemas import ChatCompletionIn, EmbeddingIn, ModelOut
from app.services import (
    consume_rpm,
    get_cached,
    list_candidate_channels,
    mark_channel_health,
    mock_chat_response,
    mock_embedding_response,
    proxy_openai,
    record_usage,
    set_cached,
    weighted_choice,
)

router = APIRouter(prefix="/v1", tags=["openai"])


@router.get("/models", response_model=list[ModelOut], summary="List logical models")
async def list_models(db: AsyncSession = Depends(get_db)) -> list[ModelOut]:
    result = await db.execute(select(models).order_by(models.c.name))
    return [ModelOut(**row) for row in result.mappings().all()]


@router.post("/chat/completions", summary="OpenAI compatible chat completions")
async def chat_completions(
    payload: ChatCompletionIn,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    candidates = await list_candidate_channels(db, payload.model, "llm")
    if not candidates:
        raise HTTPException(status_code=404, detail="model_channel_not_found")

    request_payload = payload.model_dump(exclude_none=True)
    if payload.stream:
        channel = weighted_choice(candidates)
        return StreamingResponse(
            mock_chat_stream(payload.model, [message.model_dump() for message in payload.messages]),
            media_type="text/event-stream",
        )

    cached = await get_cached(redis, "chat", request_payload)
    if cached is not None:
        cached["cache_hit"] = True
        channel = weighted_choice(candidates)
        await record_usage(db, channel, cached, latency_ms=0, cache_hit=True)
        return cached

    started = time.perf_counter()
    last_error = "model_call_failed"
    for channel in candidates:
        if not await consume_rpm(redis, channel):
            last_error = "rate_limited"
            continue
        try:
            if channel["base_url"].startswith("mock://"):
                response = mock_chat_response(payload.model, [message.model_dump() for message in payload.messages])
            else:
                response = await proxy_openai("/v1/chat/completions", channel, request_payload)
            latency_ms = int((time.perf_counter() - started) * 1000)
            await mark_channel_health(db, channel["id"], "ok")
            await set_cached(redis, "chat", request_payload, response)
            await record_usage(db, channel, response, latency_ms=latency_ms, cache_hit=False)
            return response
        except Exception:
            await mark_channel_health(db, channel["id"], "failed")
            last_error = "channel_failed"

    raise HTTPException(status_code=429 if last_error == "rate_limited" else 502, detail=last_error)


@router.post("/embeddings", summary="OpenAI compatible embeddings")
async def embeddings(
    payload: EmbeddingIn,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    candidates = await list_candidate_channels(db, payload.model, "embedding")
    if not candidates:
        raise HTTPException(status_code=404, detail="model_channel_not_found")

    request_payload = payload.model_dump()
    cached = await get_cached(redis, "embedding", request_payload)
    if cached is not None:
        cached["cache_hit"] = True
        channel = weighted_choice(candidates)
        await record_usage(db, channel, cached, latency_ms=0, cache_hit=True)
        return cached

    inputs = payload.input if isinstance(payload.input, list) else [payload.input]
    started = time.perf_counter()
    last_error = "model_call_failed"
    for channel in candidates:
        if not await consume_rpm(redis, channel):
            last_error = "rate_limited"
            continue
        try:
            if channel["base_url"].startswith("mock://"):
                response = mock_embedding_response(payload.model, inputs)
            else:
                response = await proxy_openai("/v1/embeddings", channel, request_payload)
            latency_ms = int((time.perf_counter() - started) * 1000)
            await mark_channel_health(db, channel["id"], "ok")
            await set_cached(redis, "embedding", request_payload, response)
            await record_usage(db, channel, response, latency_ms=latency_ms, cache_hit=False)
            return response
        except Exception:
            await mark_channel_health(db, channel["id"], "failed")
            last_error = "channel_failed"

    raise HTTPException(status_code=429 if last_error == "rate_limited" else 502, detail=last_error)


async def mock_chat_stream(model: str, messages: list[dict[str, str | None]]) -> AsyncGenerator[str, None]:
    response = mock_chat_response(model, messages)
    content = response["choices"][0]["message"]["content"]
    chunk_id = response["id"]
    created = int(time.time())

    for token in content.split():
        chunk = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {"content": token + " "}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    done = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"
