import asyncio
import os
from uuid import uuid4

import pytest

os.environ.setdefault("MAAS_ENCRYPTION_KEY", "test-maas-encryption-key")
os.environ.setdefault("MAAS_ADMIN_TOKEN", "test-token")

from app import services  # noqa: E402


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.deleted: list[str] = []

    async def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, ttl: int) -> None:
        self.ttls[key] = ttl

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.values.pop(key, None)
        self.ttls.pop(key, None)


def run_async(awaitable):
    return asyncio.run(awaitable)


def test_register_channel_failure_trips_only_at_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()
    db = object()
    channel_id = uuid4()
    health_updates: list[tuple[object, str]] = []

    async def fake_mark_channel_health(db, channel_id, health):
        health_updates.append((channel_id, health))

    monkeypatch.setattr(services, "mark_channel_health", fake_mark_channel_health)

    first = run_async(services.register_channel_failure(redis, db, channel_id, threshold=3))
    second = run_async(services.register_channel_failure(redis, db, channel_id, threshold=3))
    third = run_async(services.register_channel_failure(redis, db, channel_id, threshold=3))

    assert [first, second, third] == [1, 2, 3]
    assert health_updates == [(channel_id, "failed")]
    assert services.channel_failure_key(channel_id) not in redis.values


def test_register_channel_success_clears_failure_count(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()
    db = object()
    channel_id = uuid4()
    health_updates: list[tuple[object, str]] = []

    async def fake_mark_channel_health(db, channel_id, health):
        health_updates.append((channel_id, health))

    monkeypatch.setattr(services, "mark_channel_health", fake_mark_channel_health)

    run_async(services.register_channel_failure(redis, db, channel_id, threshold=3))
    run_async(services.register_channel_success(redis, db, channel_id))
    next_failure = run_async(services.register_channel_failure(redis, db, channel_id, threshold=3))

    assert next_failure == 1
    assert health_updates == [(channel_id, "ok")]
    assert redis.values[services.channel_failure_key(channel_id)] == 1
