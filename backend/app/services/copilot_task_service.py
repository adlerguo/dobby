from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.errors import NotFoundError, ValidationError
from app.models import CopilotTask, CopilotTaskStep
from app.schemas.copilot_task import CopilotTaskCreate, CopilotTaskOut, CopilotTaskPlan
from app.services.audit_service import write_audit
from app.services.copilot_task_events import append_task_event


async def create_copilot_task(
    db: AsyncSession, *, auth: AuthContext, payload: CopilotTaskCreate
) -> CopilotTaskOut:
    task = CopilotTask(
        id=uuid4(),
        tenant_id=auth.tenant_id,
        workspace_id=payload.workspace_id,
        user_id=auth.user_id,
        conversation_id=payload.conversation_id,
        title=payload.plan.title,
        user_goal=payload.plan.goal,
        plan_version=1,
        status="planned",
        progress_percent=0,
        plan=payload.plan.model_dump(mode="json"),
        warnings=payload.plan.warnings,
    )
    db.add(task)
    await db.flush()
    for step in payload.plan.steps:
        db.add(
            CopilotTaskStep(
                id=uuid4(),
                tenant_id=auth.tenant_id,
                task_id=task.id,
                step_order=step.order,
                client_step_id=step.clientStepId,
                title=step.title,
                description=step.description,
                tool_name=step.toolName,
                tool_arguments=step.toolArguments,
                dependencies=step.dependencies,
                wait_condition=step.waitCondition.model_dump(mode="json") if step.waitCondition else None,
                risk_level=step.riskLevel,
                requires_confirmation=step.requiresConfirmation,
                status="pending",
                retry_count=0,
                max_retries=2,
                idempotency_key=f"{task.id}:{task.plan_version}:{step.clientStepId}:{step.toolName}",
            )
        )
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="copilot.task_plan_created",
        resource_type="copilot_task",
        resource_id=task.id,
        detail={"task_id": str(task.id), "conversation_id": payload.conversation_id, "workspace_id": str(payload.workspace_id) if payload.workspace_id else None},
        commit=False,
    )
    await append_task_event(db, task=task, event_type="task.created", payload={"title": task.title})
    await append_task_event(db, task=task, event_type="task.planned", payload={"step_count": len(payload.plan.steps)})
    await db.commit()
    return await get_copilot_task_out(db, auth=auth, task_id=task.id)


async def list_copilot_tasks(
    db: AsyncSession, *, auth: AuthContext, status: str | None = None, limit: int = 20
) -> list[CopilotTaskOut]:
    stmt = select(CopilotTask).where(CopilotTask.tenant_id == auth.tenant_id, CopilotTask.user_id == auth.user_id)
    if status:
        stmt = stmt.where(CopilotTask.status == status)
    result = await db.execute(stmt.order_by(CopilotTask.updated_at.desc()).limit(limit))
    return [await task_out(db, task) for task in result.scalars().all()]


async def get_copilot_task_out(db: AsyncSession, *, auth: AuthContext, task_id: UUID) -> CopilotTaskOut:
    task = await get_owned_task(db, auth=auth, task_id=task_id)
    return await task_out(db, task)


async def confirm_copilot_task(db: AsyncSession, *, auth: AuthContext, task_id: UUID) -> CopilotTaskOut:
    task = await get_owned_task(db, auth=auth, task_id=task_id)
    if task.status not in {"planned", "waiting_confirmation", "paused", "failed"}:
        raise ValidationError(code="copilot_task_not_confirmable", message="当前任务状态不能确认")
    task.status = "queued"
    task.started_at = task.started_at or now()
    steps = await load_steps(db, task.id)
    for step in steps:
        if step.status in {"failed", "paused", "waiting_dependency"}:
            step.status = "pending"
            step.error_code = None
            step.error_message = None
    await append_task_event(db, task=task, event_type="confirmation.received", payload={"plan_version": task.plan_version})
    await append_task_event(db, task=task, event_type="task.queued", payload={"step_count": len(steps)})
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="copilot.task_confirmed",
        resource_type="copilot_task",
        resource_id=task.id,
        detail={"task_id": str(task.id)},
        commit=False,
    )
    await db.commit()
    return await task_out(db, task)


async def pause_copilot_task(db: AsyncSession, *, auth: AuthContext, task_id: UUID) -> CopilotTaskOut:
    task = await get_owned_task(db, auth=auth, task_id=task_id)
    task.status = "paused"
    await append_task_event(db, task=task, event_type="task.paused")
    await audit_task_action(db, auth=auth, task=task, action="copilot.task_paused")
    return await task_out(db, task)


async def resume_copilot_task(db: AsyncSession, *, auth: AuthContext, task_id: UUID) -> CopilotTaskOut:
    task = await get_owned_task(db, auth=auth, task_id=task_id)
    if task.status not in {"paused", "failed", "waiting_external"}:
        raise ValidationError(code="copilot_task_not_resumable", message="当前任务状态不能恢复")
    task.status = "queued"
    await append_task_event(db, task=task, event_type="task.resumed")
    await audit_task_action(db, auth=auth, task=task, action="copilot.task_resumed")
    return await task_out(db, task)


async def cancel_copilot_task(db: AsyncSession, *, auth: AuthContext, task_id: UUID, reason: str | None = None) -> CopilotTaskOut:
    task = await get_owned_task(db, auth=auth, task_id=task_id)
    task.status = "cancelled"
    task.cancelled_at = now()
    task.cancellation_reason = reason
    steps = await load_steps(db, task.id)
    for step in steps:
        if step.status not in {"succeeded", "failed"}:
            step.status = "cancelled"
    await append_task_event(db, task=task, event_type="task.cancelled", payload={"reason": reason})
    await audit_task_action(db, auth=auth, task=task, action="copilot.task_cancelled", detail={"reason": reason})
    return await task_out(db, task)


async def retry_copilot_task(db: AsyncSession, *, auth: AuthContext, task_id: UUID) -> CopilotTaskOut:
    task = await get_owned_task(db, auth=auth, task_id=task_id)
    steps = await load_steps(db, task.id)
    for step in steps:
        if step.status == "failed":
            step.status = "pending"
            step.error_code = None
            step.error_message = None
            step.next_retry_at = None
    task.status = "queued"
    await append_task_event(db, task=task, event_type="step.retrying", payload={"failed_steps": [str(step.id) for step in steps if step.status == "pending"]})
    await append_task_event(db, task=task, event_type="task.queued")
    await audit_task_action(db, auth=auth, task=task, action="copilot.task_step_retry")
    return await task_out(db, task)


async def get_owned_task(db: AsyncSession, *, auth: AuthContext, task_id: UUID) -> CopilotTask:
    task = await db.get(CopilotTask, task_id)
    if task is None or task.tenant_id != auth.tenant_id or task.user_id != auth.user_id:
        raise NotFoundError(code="copilot_task_not_found", message="任务不存在")
    return task


async def load_steps(db: AsyncSession, task_id: UUID) -> list[CopilotTaskStep]:
    result = await db.execute(select(CopilotTaskStep).where(CopilotTaskStep.task_id == task_id).order_by(CopilotTaskStep.step_order))
    return list(result.scalars().all())


async def task_out(db: AsyncSession, task: CopilotTask) -> CopilotTaskOut:
    steps = await load_steps(db, task.id)
    raw = CopilotTaskOut.model_validate(task)
    raw.steps = [step_out(step) for step in steps]
    return raw


def step_out(step: CopilotTaskStep):
    from app.schemas.copilot_task import CopilotTaskStepOut

    data = CopilotTaskStepOut.model_validate(step)
    data.dependencies = list(step.dependencies or [])
    data.tool_arguments = dict(step.tool_arguments or {})
    return data


async def audit_task_action(db: AsyncSession, *, auth: AuthContext, task: CopilotTask, action: str, detail: dict | None = None) -> None:
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action=action,
        resource_type="copilot_task",
        resource_id=task.id,
        detail={"task_id": str(task.id), **(detail or {})},
        commit=False,
    )
    await db.commit()


def now() -> datetime:
    return datetime.now(timezone.utc)
