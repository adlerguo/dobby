import asyncio
import logging
import time
from uuid import UUID

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import model_channels
from app.services import mark_channel_health, probe_persisted_channel

logger = logging.getLogger(__name__)


async def channel_health_probe_loop(stop_event: asyncio.Event) -> None:
    failed_seen_at: dict[UUID, float] = {}
    interval = max(int(settings.channel_health_probe_interval), 1)
    failed_ttl = max(int(settings.channel_failed_ttl), 0)

    while not stop_event.is_set():
        try:
            await probe_failed_channels(failed_seen_at, failed_ttl)
        except Exception as exc:
            logger.debug("channel health probe cycle failed: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


async def probe_failed_channels(failed_seen_at: dict[UUID, float], failed_ttl: int) -> None:
    async with SessionLocal() as db:
        result = await db.execute(
            select(model_channels.c.id).where(
                model_channels.c.status == "active",
                model_channels.c.health == "failed",
            )
        )
        channel_ids = list(result.scalars().all())

        now = time.monotonic()
        active_failed = set(channel_ids)
        for channel_id in list(failed_seen_at):
            if channel_id not in active_failed:
                failed_seen_at.pop(channel_id, None)

        for channel_id in channel_ids:
            first_seen = failed_seen_at.setdefault(channel_id, now)
            if now - first_seen < failed_ttl:
                continue

            result = await probe_persisted_channel(db, channel_id)
            if result.health != "ok":
                logger.debug("channel health probe still failed channel_id=%s error=%s", channel_id, result.error)
                continue

            await mark_channel_health(db, channel_id, "ok")
            failed_seen_at.pop(channel_id, None)
            logger.info("channel recovered from failed health channel_id=%s", channel_id)
