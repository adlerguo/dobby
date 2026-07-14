import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from redis.asyncio import Redis

from app.core.api_key_auth import AppApiKeyContext
from app.core.config import settings


@dataclass(frozen=True)
class PublicKeyLimits:
    rate_limit_per_minute: int
    daily_request_quota: int
    daily_token_quota: int
    daily_cost_quota: float


REQUEST_QUOTA_SCRIPT = """
local key = KEYS[1]
local quota = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local current = tonumber(redis.call('HGET', key, 'requests') or '0')
if quota > 0 and current >= quota then
  return -1
end
local next_value = redis.call('HINCRBY', key, 'requests', 1)
redis.call('EXPIRE', key, ttl)
return next_value
"""


async def enforce_public_key_limits(redis: Redis, auth: AppApiKeyContext) -> None:
    limits = resolve_limits(auth.config)
    await enforce_rate_limit(redis, auth.key_id, limits.rate_limit_per_minute)
    await enforce_daily_usage_available(redis, auth.key_id, limits)
    await reserve_daily_request(redis, auth.key_id, limits.daily_request_quota)


async def record_public_key_usage(redis: Redis, auth: AppApiKeyContext, usage: dict[str, Any]) -> None:
    limits = resolve_limits(auth.config)
    key = daily_quota_key(auth.key_id)
    ttl = seconds_until_tomorrow()
    tokens = int((usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0) or usage.get("total_tokens") or 0)
    cost_micros = int(float(usage.get("cost") or 0) * 1_000_000)
    pipe = redis.pipeline(transaction=True)
    if tokens:
        pipe.hincrby(key, "tokens", tokens)
    if cost_micros:
        pipe.hincrby(key, "cost_micros", cost_micros)
    pipe.expire(key, ttl)
    await pipe.execute()


async def enforce_rate_limit(redis: Redis, key_id: Any, limit: int) -> None:
    if limit <= 0:
        return
    now = int(time.time())
    window = now // 60
    key = f"public:key:{key_id}:rate:{window}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 70)
    if int(count) > limit:
        retry_after = 60 - (now % 60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": {"code": "rate_limited", "message": "Public app API key rate limit exceeded."}},
            headers={"Retry-After": str(retry_after)},
        )


async def enforce_daily_usage_available(redis: Redis, key_id: Any, limits: PublicKeyLimits) -> None:
    usage = await redis.hgetall(daily_quota_key(key_id))
    tokens = int(usage.get("tokens") or 0)
    cost_micros = int(usage.get("cost_micros") or 0)
    if limits.daily_token_quota > 0 and tokens >= limits.daily_token_quota:
        raise quota_exceeded("daily_token_quota_exceeded")
    if limits.daily_cost_quota > 0 and cost_micros >= int(limits.daily_cost_quota * 1_000_000):
        raise quota_exceeded("daily_cost_quota_exceeded")


async def reserve_daily_request(redis: Redis, key_id: Any, quota: int) -> None:
    if quota <= 0:
        return
    result = await redis.eval(REQUEST_QUOTA_SCRIPT, 1, daily_quota_key(key_id), quota, seconds_until_tomorrow())
    if int(result) < 0:
        raise quota_exceeded("daily_request_quota_exceeded")


def quota_exceeded(code: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail={"error": {"code": code, "message": "Public app API key quota exceeded."}},
    )


def resolve_limits(config: dict[str, Any]) -> PublicKeyLimits:
    limits = config.get("limits") if isinstance(config.get("limits"), dict) else config
    return PublicKeyLimits(
        rate_limit_per_minute=coerce_int(limits.get("rate_limit_per_minute"), settings.public_app_rate_limit_per_minute),
        daily_request_quota=coerce_int(limits.get("daily_request_quota"), settings.public_app_daily_request_quota),
        daily_token_quota=coerce_int(limits.get("daily_token_quota"), settings.public_app_daily_token_quota),
        daily_cost_quota=coerce_float(limits.get("daily_cost_quota"), settings.public_app_daily_cost_quota),
    )


def coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def daily_quota_key(key_id: Any) -> str:
    day = datetime.now(UTC).strftime("%Y%m%d")
    return f"public:key:{key_id}:quota:{day}"


def seconds_until_tomorrow() -> int:
    now = datetime.now(UTC)
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    return max(math.ceil((tomorrow - now).total_seconds()), 60)
