from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CopilotTask, CopilotTaskEvent, CopilotTaskStep
from app.schemas.copilot_task import CopilotTaskEventOut

SENSITIVE_KEYS = {"api_key", "password", "token", "secret", "authorization"}


async def append_task_event(
    db: AsyncSession,
    *,
    task: CopilotTask,
    event_type: str,
    step: CopilotTaskStep | None = None,
    payload: dict[str, Any] | None = None,
) -> CopilotTaskEvent:
    next_event_id = await next_task_event_id(db, task.id)
    event = CopilotTaskEvent(
        id=uuid4(),
        tenant_id=task.tenant_id,
        workspace_id=task.workspace_id,
        task_id=task.id,
        step_id=step.id if step else None,
        event_id=next_event_id,
        event_type=event_type,
        payload=sanitize_event_payload(
            {
                "task_id": str(task.id),
                "task_status": task.status,
                "step_id": str(step.id) if step else None,
                "step_status": step.status if step else None,
                **(payload or {}),
            }
        ),
    )
    db.add(event)
    await db.flush()
    return event


async def next_task_event_id(db: AsyncSession, task_id: UUID) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(CopilotTaskEvent.event_id), 0)).where(
            CopilotTaskEvent.task_id == task_id
        )
    )
    return int(result.scalar_one()) + 1


async def list_task_events(
    db: AsyncSession,
    *,
    task: CopilotTask,
    after_event_id: int = 0,
    limit: int = 100,
) -> list[CopilotTaskEventOut]:
    result = await db.execute(
        select(CopilotTaskEvent)
        .where(
            CopilotTaskEvent.tenant_id == task.tenant_id,
            CopilotTaskEvent.task_id == task.id,
            CopilotTaskEvent.event_id > after_event_id,
        )
        .order_by(CopilotTaskEvent.event_id)
        .limit(limit)
    )
    return [CopilotTaskEventOut.model_validate(event) for event in result.scalars().all()]


def sanitize_event_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "***" if key.lower() in SENSITIVE_KEYS else sanitize_event_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_event_payload(item) for item in value]
    return value
