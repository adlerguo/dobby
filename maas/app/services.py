import hashlib
import json
import random
import time
from typing import Any
from uuid import UUID

import httpx
from redis.asyncio import Redis
from sqlalchemy import and_, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.models import model_channels, models, usage_records
from app.schemas import ChannelCreate, ChannelOut, ChannelProbeIn, ChannelProbeOut, ChannelUpdate


async def ensure_model(db: AsyncSession, name: str, model_type: str, provider: str | None) -> UUID:
    result = await db.execute(select(models).where(models.c.name == name))
    row = result.mappings().first()
    if row is not None:
        return row["id"]

    result = await db.execute(
        insert(models)
        .values(name=name, provider=provider, type=model_type)
        .returning(models.c.id)
    )
    return result.scalar_one()


async def create_channel(db: AsyncSession, payload: ChannelCreate) -> ChannelOut:
    model_id = await ensure_model(db, payload.model, payload.model_type, payload.provider)
    result = await db.execute(
        insert(model_channels)
        .values(
            tenant_id=payload.tenant_id,
            model_id=model_id,
            base_url=payload.base_url,
            api_key_enc=encrypt_secret(payload.api_key),
            weight=payload.weight,
            rpm_limit=payload.rpm_limit,
            status=payload.status,
            health="unknown",
        )
        .returning(model_channels.c.id)
    )
    channel_id = result.scalar_one()
    await db.commit()
    return await get_channel(db, channel_id)


async def list_channels(db: AsyncSession) -> list[ChannelOut]:
    stmt = (
        select(
            model_channels,
            models.c.name.label("model"),
            models.c.type.label("model_type"),
            models.c.provider.label("provider"),
        )
        .join(models, models.c.id == model_channels.c.model_id, isouter=True)
        .order_by(model_channels.c.created_at.desc())
    )
    result = await db.execute(stmt)
    return [channel_out(row) for row in result.mappings().all()]


async def get_channel(db: AsyncSession, channel_id: UUID) -> ChannelOut:
    stmt = (
        select(
            model_channels,
            models.c.name.label("model"),
            models.c.type.label("model_type"),
            models.c.provider.label("provider"),
        )
        .join(models, models.c.id == model_channels.c.model_id, isouter=True)
        .where(model_channels.c.id == channel_id)
    )
    result = await db.execute(stmt)
    row = result.mappings().first()
    if row is None:
        raise ValueError("channel_not_found")
    return channel_out(row)


async def get_channel_row(db: AsyncSession, channel_id: UUID) -> dict[str, Any]:
    stmt = (
        select(
            model_channels,
            models.c.name.label("model"),
            models.c.type.label("model_type"),
            models.c.provider.label("provider"),
            models.c.provider_config.label("provider_config"),
        )
        .join(models, models.c.id == model_channels.c.model_id, isouter=True)
        .where(model_channels.c.id == channel_id)
    )
    result = await db.execute(stmt)
    row = result.mappings().first()
    if row is None:
        raise ValueError("channel_not_found")
    return dict(row)


async def update_channel(db: AsyncSession, channel_id: UUID, payload: ChannelUpdate) -> ChannelOut:
    values = payload.model_dump(exclude_unset=True)
    api_key = values.pop("api_key", None)
    if api_key is not None:
        values["api_key_enc"] = encrypt_secret(api_key)
    if values:
        await db.execute(update(model_channels).where(model_channels.c.id == channel_id).values(**values))
        await db.commit()
    return await get_channel(db, channel_id)


async def delete_channel(db: AsyncSession, channel_id: UUID) -> None:
    await db.execute(update(model_channels).where(model_channels.c.id == channel_id).values(status="disabled"))
    await db.commit()


async def choose_channel(db: AsyncSession, model_name: str, model_type: str) -> dict[str, Any] | None:
    candidates = await list_candidate_channels(db, model_name, model_type)
    if not candidates:
        return None
    return weighted_choice(candidates)


async def list_candidate_channels(db: AsyncSession, model_name: str, model_type: str) -> list[dict[str, Any]]:
    stmt = (
        select(model_channels, models.c.name.label("model"), models.c.type.label("model_type"))
        .add_columns(models.c.provider.label("provider"), models.c.provider_config.label("provider_config"))
        .join(models, models.c.id == model_channels.c.model_id)
        .where(
            and_(
                models.c.name == model_name,
                models.c.type == model_type,
                model_channels.c.status == "active",
                model_channels.c.health != "failed",
            )
        )
        .order_by(model_channels.c.weight.desc(), model_channels.c.created_at.asc())
    )
    result = await db.execute(stmt)
    return [dict(row) for row in result.mappings().all()]


def weighted_choice(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    weights = [max(int(candidate.get("weight") or 1), 1) for candidate in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]


def channel_out(row: dict[str, Any]) -> ChannelOut:
    return ChannelOut(
        id=row["id"],
        tenant_id=row["tenant_id"],
        model_id=row["model_id"],
        model=row.get("model"),
        model_type=row.get("model_type"),
        provider=row.get("provider"),
        base_url=row["base_url"],
        weight=row["weight"],
        rpm_limit=row["rpm_limit"],
        status=row["status"],
        health=row["health"],
    )


def mock_chat_response(model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    user_text = next((m.get("content") or "" for m in reversed(messages) if m.get("role") == "user"), "")
    content = f"mock response: {user_text}" if user_text else "mock response"
    now = int(time.time())
    return {
        "id": f"chatcmpl-mock-{now}",
        "object": "chat.completion",
        "created": now,
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": sum(len((m.get("content") or "").split()) for m in messages),
            "completion_tokens": len(content.split()),
            "total_tokens": sum(len((m.get("content") or "").split()) for m in messages) + len(content.split()),
        },
    }


def mock_embedding_response(model: str, inputs: list[str]) -> dict[str, Any]:
    data = []
    for index, text in enumerate(inputs):
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed = [byte / 255 for byte in digest]
        embedding = (seed * ((1536 // len(seed)) + 1))[:1536]
        data.append({"object": "embedding", "index": index, "embedding": embedding})
    return {"object": "list", "model": model, "data": data, "usage": {"prompt_tokens": sum(len(i.split()) for i in inputs), "total_tokens": sum(len(i.split()) for i in inputs)}}


async def proxy_openai(path: str, channel: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    api_key = decrypt_secret(channel["api_key_enc"])
    return await proxy_openai_with_key(path, channel, payload, api_key=api_key)


async def proxy_openai_with_key(
    path: str,
    channel: dict[str, Any],
    payload: dict[str, Any],
    *,
    api_key: str,
) -> dict[str, Any]:
    base_url = channel["base_url"].rstrip("/")
    request_payload = dict(payload)
    provider_config = channel.get("provider_config") or {}
    upstream_model = provider_config.get("catalog_code") or provider_config.get("upstream_model")
    if upstream_model:
        request_payload["model"] = upstream_model
    if channel.get("provider") == "deepseek" and path == "/v1/chat/completions":
        request_payload["model"] = upstream_model or "deepseek-chat"
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{base_url}{path}",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=request_payload,
        )
        response.raise_for_status()
        return response.json()


async def probe_transient_channel(payload: ChannelProbeIn) -> ChannelProbeOut:
    if payload.protocol not in {"mock", "openai_compatible"}:
        return ChannelProbeOut(ok=False, health="failed", error="protocol_not_supported")
    if payload.model_type == "rerank":
        return ChannelProbeOut(ok=False, health="failed", error="model_type_not_supported")
    if payload.base_url.startswith("mock://") or payload.protocol == "mock":
        return ChannelProbeOut(ok=True, health="ok")

    channel = {
        "base_url": payload.base_url,
        "provider": payload.provider,
        "provider_config": {"catalog_code": payload.model},
    }
    return await probe_channel_request(
        channel,
        model=payload.model,
        model_type=payload.model_type,
        api_key=payload.api_key,
    )


async def probe_persisted_channel(db: AsyncSession, channel_id: UUID) -> ChannelProbeOut:
    channel = await get_channel_row(db, channel_id)
    if channel["base_url"].startswith("mock://"):
        return ChannelProbeOut(ok=True, health="ok")
    if channel.get("model_type") == "rerank":
        return ChannelProbeOut(ok=False, health="failed", error="model_type_not_supported")
    api_key = decrypt_secret(channel["api_key_enc"])
    return await probe_channel_request(
        channel,
        model=channel.get("model") or "unknown",
        model_type=channel.get("model_type") or "llm",
        api_key=api_key,
    )


async def probe_channel_request(
    channel: dict[str, Any],
    *,
    model: str,
    model_type: str,
    api_key: str,
) -> ChannelProbeOut:
    try:
        if model_type == "llm":
            await proxy_openai_with_key(
                "/v1/chat/completions",
                channel,
                {
                    "model": model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 8,
                    "stream": False,
                },
                api_key=api_key,
            )
        elif model_type == "embedding":
            await proxy_openai_with_key(
                "/v1/embeddings",
                channel,
                {"model": model, "input": "ping"},
                api_key=api_key,
            )
        else:
            return ChannelProbeOut(ok=False, health="failed", error="model_type_not_supported")
        return ChannelProbeOut(ok=True, health="ok")
    except Exception as exc:
        return ChannelProbeOut(ok=False, health="failed", error=summarize_probe_error(exc))


def summarize_probe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"provider_http_{exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "provider_timeout"
    if isinstance(exc, httpx.RequestError):
        return "provider_request_failed"
    return "provider_probe_failed"


def exact_cache_key(kind: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"maas:cache:{kind}:{digest}"


async def get_cached(redis: Redis, kind: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    cached = await redis.get(exact_cache_key(kind, payload))
    if cached is None:
        return None
    return json.loads(cached)


async def set_cached(redis: Redis, kind: str, payload: dict[str, Any], response: dict[str, Any]) -> None:
    await redis.setex(exact_cache_key(kind, payload), settings.maas_cache_ttl, json.dumps(response, ensure_ascii=False))


async def consume_rpm(redis: Redis, channel: dict[str, Any]) -> bool:
    rpm_limit = channel.get("rpm_limit")
    if rpm_limit is None:
        return True

    minute = int(time.time() // 60)
    key = f"maas:rpm:{channel['id']}:{minute}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 70)
    return count <= int(rpm_limit)


async def mark_channel_health(db: AsyncSession, channel_id: UUID, health: str) -> None:
    await db.execute(update(model_channels).where(model_channels.c.id == channel_id).values(health=health))
    await db.commit()


async def record_usage(
    db: AsyncSession,
    channel: dict[str, Any],
    response: dict[str, Any],
    *,
    latency_ms: int,
    cache_hit: bool,
) -> None:
    tenant_id = channel.get("tenant_id")
    if tenant_id is None:
        return

    usage = response.get("usage") or {}
    await db.execute(
        insert(usage_records).values(
            tenant_id=tenant_id,
            channel_id=channel["id"],
            model_id=channel["model_id"],
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            latency_ms=latency_ms,
            cost=0,
            cache_hit=cache_hit,
        )
    )
    await db.commit()
