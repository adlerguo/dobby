import asyncio
import logging
import os
import signal
from uuid import uuid4

from app.core.config import settings

logger = logging.getLogger("computer_use_worker")


class WorkerStop:
    stopping = False


def install_signal_handlers() -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, setattr, WorkerStop, "stopping", True)


async def worker_loop(worker_id: str, poll_interval: float = 2.0) -> None:
    while not WorkerStop.stopping:
        if not settings.computer_use_enabled:
            await asyncio.sleep(poll_interval)
            continue
        logger.info("computer use worker idle: %s", worker_id)
        await asyncio.sleep(poll_interval)


async def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    worker_id = os.getenv("COMPUTER_USE_WORKER_ID") or f"computer-use-worker-{uuid4()}"
    install_signal_handlers()
    logger.info("computer use worker started: %s enabled=%s", worker_id, settings.computer_use_enabled)
    await worker_loop(worker_id, poll_interval=float(os.getenv("COMPUTER_USE_WORKER_POLL_INTERVAL", "2")))
    logger.info("computer use worker stopped: %s", worker_id)


if __name__ == "__main__":
    asyncio.run(main())
