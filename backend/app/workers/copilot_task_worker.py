import asyncio
import logging
import os
import signal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, get_permission_codes, get_role_codes
from app.core.database import SessionLocal
from app.models import CopilotTask, Tenant, User
from app.services.copilot_task_executor import run_one_copilot_worker_tick
from app.services.copilot_task_recovery import recover_interrupted_copilot_tasks

logger = logging.getLogger("copilot_task_worker")


class WorkerStop:
    stopping = False


async def load_task_auth(db: AsyncSession, task: CopilotTask) -> AuthContext:
    user = await db.get(User, task.user_id)
    tenant = await db.get(Tenant, task.tenant_id)
    if user is None or tenant is None:
        raise RuntimeError("copilot_task_identity_missing")
    roles = await get_role_codes(db, user.id)
    permissions = await get_permission_codes(db, user.id)
    return AuthContext(user=user, tenant=tenant, roles=roles, permissions=permissions)


async def worker_loop(worker_id: str, poll_interval: float = 2.0) -> None:
    async with SessionLocal() as db:
        recovered = await recover_interrupted_copilot_tasks(db)
        if any(recovered.values()):
            logger.info("startup recovery: %s", recovered)

    while not WorkerStop.stopping:
        did_work = False
        try:
            async with SessionLocal() as db:
                did_work = await run_one_copilot_worker_tick(
                    db,
                    worker_id=worker_id,
                    auth_loader=load_task_auth,
                )
        except Exception:
            logger.exception("copilot worker tick failed")
        if not did_work:
            await asyncio.sleep(poll_interval)


def install_signal_handlers() -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, setattr, WorkerStop, "stopping", True)


async def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    worker_id = os.getenv("COPILOT_WORKER_ID") or f"copilot-worker-{uuid4()}"
    install_signal_handlers()
    logger.info("copilot task worker started: %s", worker_id)
    await worker_loop(worker_id, poll_interval=float(os.getenv("COPILOT_WORKER_POLL_INTERVAL", "2")))
    logger.info("copilot task worker stopped: %s", worker_id)


if __name__ == "__main__":
    asyncio.run(main())
