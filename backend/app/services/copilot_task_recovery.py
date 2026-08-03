from datetime import datetime, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CopilotTask, CopilotTaskStep


async def recover_interrupted_copilot_tasks(db: AsyncSession) -> dict[str, int]:
    ts = datetime.now(timezone.utc)
    expired_running_steps = await db.execute(
        update(CopilotTaskStep)
        .where(
            CopilotTaskStep.status == "running",
            or_(
                CopilotTaskStep.lease_expires_at.is_(None),
                CopilotTaskStep.lease_expires_at <= ts,
            ),
        )
        .values(
            status="paused",
            error_code="recovery_manual_check_required",
            error_message="服务重启恢复时步骤租约已失效，已暂停等待人工确认。",
            claimed_by=None,
            claimed_at=None,
            lease_expires_at=None,
            heartbeat_at=None,
        )
    )
    running_tasks = await db.execute(
        update(CopilotTask)
        .where(
            CopilotTask.status == "running",
            CopilotTask.current_step_id.in_(
                select(CopilotTaskStep.id).where(CopilotTaskStep.status == "paused")
            ),
        )
        .values(
            status="paused",
            error_code="recovery_manual_check_required",
            error_message="服务重启恢复时当前步骤租约已失效，已暂停等待人工确认。",
        )
    )
    retry_tasks = await db.execute(
        update(CopilotTask)
        .where(CopilotTask.status.in_(["retrying"]))
        .values(status="queued")
    )
    retry_steps = await db.execute(
        update(CopilotTaskStep)
        .where(CopilotTaskStep.status == "retrying", CopilotTaskStep.next_retry_at.is_(None))
        .values(next_retry_at=ts)
    )
    await db.commit()
    return {
        "paused_running_tasks": running_tasks.rowcount or 0,
        "paused_expired_running_steps": expired_running_steps.rowcount or 0,
        "requeued_retrying_tasks": retry_tasks.rowcount or 0,
        "normalized_retrying_steps": retry_steps.rowcount or 0,
    }
