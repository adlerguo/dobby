from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.errors import AppError
from app.models import Agent, CopilotTask, CopilotTaskStep, KnowledgeBase
from app.schemas.copilot import CopilotExecuteIn
from app.services.audit_service import write_audit
from app.services.copilot_service import execute_copilot_tool
from app.services.copilot_task_events import append_task_event
from app.services.copilot_task_service import get_copilot_task_out, load_steps


TERMINAL_TASK_STATUSES = {"succeeded", "partially_succeeded", "failed", "cancelled"}
TERMINAL_STEP_STATUSES = {"succeeded", "failed", "skipped", "cancelled"}
RETRYABLE_ERROR_CODES = {"database_unavailable", "maas_timeout", "dependency_unavailable", "lock_timeout", "rate_limited"}
DEFAULT_LEASE_SECONDS = 120
MAX_CHECK_INTERVAL_SECONDS = 60


async def run_copilot_task_until_blocked(
    db: AsyncSession,
    *,
    auth: AuthContext,
    task_id: UUID,
    request: Request | None = None,
):
    task = await db.get(CopilotTask, task_id)
    if task is None or task.tenant_id != auth.tenant_id or task.user_id != auth.user_id:
        return await get_copilot_task_out(db, auth=auth, task_id=task_id)
    if task.status in TERMINAL_TASK_STATUSES:
        return await get_copilot_task_out(db, auth=auth, task_id=task_id)

    task.status = "running"
    task.started_at = task.started_at or now()
    await db.commit()

    while task.status == "running":
        steps = await load_steps(db, task.id)
        update_progress(task, steps)
        next_step = pick_next_step(steps)
        if next_step is None:
            finish_task(task, steps)
            await write_task_audit(db, auth=auth, task=task, action=f"copilot.task_{'completed' if task.status == 'succeeded' else task.status}")
            await db.commit()
            break
        if not dependencies_succeeded(next_step, steps):
            next_step.status = "waiting_dependency"
            task.status = "waiting_external"
            await db.commit()
            break
        if next_step.risk_level == "L3" and not bool((next_step.tool_arguments or {}).get("publish_confirmed")):
            next_step.status = "waiting_confirmation"
            task.status = "waiting_confirmation"
            task.current_step_id = next_step.id
            await db.commit()
            break
        idempotent = await idempotency_result(db, task=task, step=next_step)
        if idempotent is not None:
            mark_step_succeeded(next_step, idempotent)
            await db.commit()
            continue
        await execute_step(db, auth=auth, task=task, step=next_step, steps=steps, request=request)
        await db.refresh(task)
        if task.status in {"waiting_external", "waiting_confirmation", "paused", "failed"}:
            break
    return await get_copilot_task_out(db, auth=auth, task_id=task.id)


async def execute_step(
    db: AsyncSession,
    *,
    auth: AuthContext,
    task: CopilotTask,
    step: CopilotTaskStep,
    steps: list[CopilotTaskStep],
    request: Request | None,
) -> None:
    step.status = "running"
    step.started_at = now()
    step.heartbeat_at = now()
    task.current_step_id = step.id
    await append_task_event(db, task=task, step=step, event_type="step.started", payload={"tool_name": step.tool_name})
    await db.commit()
    try:
        args = resolve_step_arguments(step.tool_arguments or {}, steps)
        payload = CopilotExecuteIn(
            tool=step.tool_name,
            input=args,
            confirmed=step.requires_confirmation or step.risk_level in {"L2", "L3"},
            conversation_id=task.conversation_id,
            workspace_id=str(task.workspace_id) if task.workspace_id else None,
        )
        result = await execute_copilot_tool(db, auth=auth, payload=payload, request=request)
        output = result.result
        if step.wait_condition and is_waiting_output(output):
            mark_step_waiting_external(step, task, output)
            await append_task_event(db, task=task, step=step, event_type="step.waiting", payload={"output": output})
        else:
            mark_step_succeeded(step, output)
            await append_task_event(db, task=task, step=step, event_type="step.succeeded", payload={"output": output})
        await write_audit(
            db,
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            action="copilot.task_step_execute",
            resource_type="copilot_task",
            resource_id=task.id,
            detail={
                "task_id": str(task.id),
                "step_id": str(step.id),
                "tool_name": step.tool_name,
                "status": step.status,
                "arguments": sanitize_args(args),
            },
            request=request,
            commit=False,
        )
        await db.commit()
    except Exception as exc:
        await handle_step_failure(db, task=task, step=step, exc=exc)


async def handle_step_failure(db: AsyncSession, *, task: CopilotTask, step: CopilotTaskStep, exc: Exception) -> None:
    code = getattr(exc, "code", None) or exc.__class__.__name__
    message = getattr(exc, "message", None) or str(exc) or "执行失败"
    retryable = code in RETRYABLE_ERROR_CODES
    if retryable and step.retry_count < step.max_retries:
        step.retry_count += 1
        step.status = "retrying"
        step.next_retry_at = now() + retry_delay(step.retry_count)
        task.status = "retrying"
        await append_task_event(db, task=task, step=step, event_type="step.retrying", payload={"error_code": str(code), "retry_count": step.retry_count})
    else:
        step.status = "failed"
        step.error_code = str(code)
        step.error_message = str(message)
        task.status = "failed"
        task.error_code = str(code)
        task.error_message = str(message)
        task.completed_at = now()
        await append_task_event(db, task=task, step=step, event_type="step.failed", payload={"error_code": str(code), "error_message": str(message)})
        await append_task_event(db, task=task, event_type="task.failed", payload={"error_code": str(code), "error_message": str(message)})
    release_step_lease(step)
    await db.commit()


async def run_one_copilot_worker_tick(
    db: AsyncSession,
    *,
    worker_id: str,
    auth_loader,
    request: Request | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> bool:
    await recover_expired_step_leases(db, worker_id=worker_id)
    waiting_step = await claim_waiting_external_step(db, worker_id=worker_id, lease_seconds=lease_seconds)
    if waiting_step is not None:
        task = await db.get(CopilotTask, waiting_step.task_id)
        if task is None:
            return True
        auth = await auth_loader(db, task)
        await check_waiting_external_step(db, auth=auth, task=task, step=waiting_step, request=request)
        await continue_ready_task(db, worker_id=worker_id, auth_loader=auth_loader, request=request, lease_seconds=lease_seconds, task_id=task.id)
        return True

    step = await claim_next_executable_step(db, worker_id=worker_id, lease_seconds=lease_seconds)
    if step is None:
        return False
    task = await db.get(CopilotTask, step.task_id)
    if task is None:
        return True
    auth = await auth_loader(db, task)
    await execute_claimed_step(db, auth=auth, task=task, step=step, request=request)
    await continue_ready_task(db, worker_id=worker_id, auth_loader=auth_loader, request=request, lease_seconds=lease_seconds, task_id=task.id)
    return True


async def continue_ready_task(
    db: AsyncSession,
    *,
    worker_id: str,
    auth_loader,
    request: Request | None,
    lease_seconds: int,
    task_id: UUID,
) -> None:
    for _ in range(20):
        task = await db.get(CopilotTask, task_id)
        if task is None or task.status in TERMINAL_TASK_STATUSES | {"paused", "waiting_external", "waiting_confirmation"}:
            return
        step = await claim_next_executable_step(db, worker_id=worker_id, lease_seconds=lease_seconds, task_id=task_id)
        if step is None:
            steps = await load_steps(db, task_id)
            if all(item.status in TERMINAL_STEP_STATUSES for item in steps):
                finish_task(task, steps)
                await append_task_event(db, task=task, event_type=f"task.{task.status}", payload={"result_summary": task.result_summary})
                await db.commit()
            return
        auth = await auth_loader(db, task)
        await execute_claimed_step(db, auth=auth, task=task, step=step, request=request)


async def claim_next_executable_step(
    db: AsyncSession,
    *,
    worker_id: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    task_id: UUID | None = None,
) -> CopilotTaskStep | None:
    ts = now()
    stmt = (
        select(CopilotTaskStep)
        .join(CopilotTask, CopilotTask.id == CopilotTaskStep.task_id)
        .where(
            CopilotTask.status.in_(["queued", "running", "retrying"]),
            CopilotTaskStep.status.in_(["pending", "queued", "retrying"]),
            or_(CopilotTaskStep.next_retry_at.is_(None), CopilotTaskStep.next_retry_at <= ts),
            or_(CopilotTaskStep.lease_expires_at.is_(None), CopilotTaskStep.lease_expires_at <= ts),
        )
        .order_by(CopilotTask.updated_at, CopilotTaskStep.step_order)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if task_id is not None:
        stmt = stmt.where(CopilotTask.id == task_id)
    result = await db.execute(stmt)
    step = result.scalar_one_or_none()
    if step is None:
        await db.commit()
        return None
    task = await db.get(CopilotTask, step.task_id)
    steps = await load_steps(db, step.task_id)
    if task is None or not dependencies_succeeded(step, steps):
        step.status = "waiting_dependency"
        if task is not None:
            task.status = "waiting_external"
            await append_task_event(db, task=task, step=step, event_type="step.waiting", payload={"reason": "waiting_dependency"})
        await db.commit()
        return None
    if step.risk_level == "L3" and not bool((step.tool_arguments or {}).get("publish_confirmed")):
        step.status = "waiting_confirmation"
        if task is not None:
            task.status = "waiting_confirmation"
            task.current_step_id = step.id
            await append_task_event(db, task=task, step=step, event_type="confirmation.required", payload={"tool_name": step.tool_name})
        await db.commit()
        return None
    claim_step(step, worker_id=worker_id, lease_seconds=lease_seconds)
    if task is not None:
        task.status = "running"
        task.started_at = task.started_at or ts
        task.current_step_id = step.id
        await append_task_event(db, task=task, step=step, event_type="step.queued", payload={"worker_id": worker_id})
    await db.commit()
    return step


async def claim_waiting_external_step(
    db: AsyncSession,
    *,
    worker_id: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> CopilotTaskStep | None:
    ts = now()
    result = await db.execute(
        select(CopilotTaskStep)
        .join(CopilotTask, CopilotTask.id == CopilotTaskStep.task_id)
        .where(
            CopilotTask.status == "waiting_external",
            CopilotTaskStep.status == "waiting_external",
            or_(CopilotTaskStep.next_check_at.is_(None), CopilotTaskStep.next_check_at <= ts),
            or_(CopilotTaskStep.lease_expires_at.is_(None), CopilotTaskStep.lease_expires_at <= ts),
        )
        .order_by(CopilotTaskStep.next_check_at.nullsfirst(), CopilotTaskStep.step_order)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    step = result.scalar_one_or_none()
    if step is None:
        await db.commit()
        return None
    claim_step(step, worker_id=worker_id, lease_seconds=lease_seconds)
    await db.commit()
    return step


async def execute_claimed_step(
    db: AsyncSession,
    *,
    auth: AuthContext,
    task: CopilotTask,
    step: CopilotTaskStep,
    request: Request | None,
) -> None:
    steps = await load_steps(db, task.id)
    idempotent = await idempotency_result(db, task=task, step=step)
    if idempotent is not None:
        mark_step_succeeded(step, idempotent)
        release_step_lease(step)
        await append_task_event(db, task=task, step=step, event_type="step.succeeded", payload={"idempotent": True, "output": idempotent})
        await db.commit()
        return
    await execute_step(db, auth=auth, task=task, step=step, steps=steps, request=request)
    release_step_lease(step)
    await db.commit()


async def check_waiting_external_step(
    db: AsyncSession,
    *,
    auth: AuthContext,
    task: CopilotTask,
    step: CopilotTaskStep,
    request: Request | None,
) -> None:
    if step.timeout_at and step.timeout_at <= now():
        step.status = "failed"
        step.error_code = "waiting_external_timeout"
        step.error_message = "等待外部资源超时"
        task.status = "failed"
        task.error_code = step.error_code
        task.error_message = step.error_message
        task.completed_at = now()
        release_step_lease(step)
        await append_task_event(db, task=task, step=step, event_type="step.failed", payload={"error_code": step.error_code})
        await append_task_event(db, task=task, event_type="task.failed", payload={"error_code": step.error_code})
        await db.commit()
        return
    try:
        steps = await load_steps(db, task.id)
        args = resolve_step_arguments(step.tool_arguments or {}, steps)
        payload = CopilotExecuteIn(
            tool=step.tool_name,
            input=args,
            confirmed=True,
            conversation_id=task.conversation_id,
            workspace_id=str(task.workspace_id) if task.workspace_id else None,
        )
        result = await execute_copilot_tool(db, auth=auth, payload=payload, request=request)
        output = result.result
        step.check_count += 1
        if is_waiting_output(output):
            mark_step_waiting_external(step, task, output)
            await append_task_event(db, task=task, step=step, event_type="step.waiting", payload={"output": output, "check_count": step.check_count})
        else:
            mark_step_succeeded(step, output)
            task.status = "queued"
            await append_task_event(db, task=task, step=step, event_type="step.succeeded", payload={"output": output})
        release_step_lease(step)
        await db.commit()
    except Exception as exc:
        await handle_step_failure(db, task=task, step=step, exc=exc)


async def recover_expired_step_leases(db: AsyncSession, *, worker_id: str) -> int:
    ts = now()
    result = await db.execute(
        select(CopilotTaskStep)
        .where(
            CopilotTaskStep.status == "running",
            CopilotTaskStep.lease_expires_at.is_not(None),
            CopilotTaskStep.lease_expires_at <= ts,
        )
        .limit(20)
        .with_for_update(skip_locked=True)
    )
    recovered = 0
    for step in result.scalars().all():
        task = await db.get(CopilotTask, step.task_id)
        if task is None:
            continue
        idempotent = await idempotency_result(db, task=task, step=step)
        if idempotent is not None:
            mark_step_succeeded(step, idempotent)
            task.status = "queued"
            await append_task_event(db, task=task, step=step, event_type="step.succeeded", payload={"recovered_by": worker_id, "idempotent": True})
        else:
            step.status = "paused"
            task.status = "paused"
            task.error_code = "worker_lease_expired"
            task.error_message = "Worker 租约过期，无法确认步骤是否完成，已暂停等待人工确认"
            await append_task_event(db, task=task, step=step, event_type="task.paused", payload={"recovered_by": worker_id, "reason": "lease_expired"})
        release_step_lease(step)
        recovered += 1
    await db.commit()
    return recovered


def pick_next_step(steps: list[CopilotTaskStep]) -> CopilotTaskStep | None:
    return next((step for step in steps if step.status in {"pending", "queued", "retrying", "waiting_external"}), None)


def dependencies_succeeded(step: CopilotTaskStep, steps: list[CopilotTaskStep]) -> bool:
    by_client_id = {item.client_step_id: item for item in steps}
    return all(by_client_id.get(dep) and by_client_id[dep].status == "succeeded" for dep in (step.dependencies or []))


def resolve_step_arguments(value: Any, steps: list[CopilotTaskStep]) -> Any:
    if isinstance(value, str) and value.startswith("$steps."):
        return resolve_reference(value, steps)
    if isinstance(value, list):
        return [resolve_step_arguments(item, steps) for item in value]
    if isinstance(value, dict):
        return {key: resolve_step_arguments(item, steps) for key, item in value.items()}
    return value


def resolve_reference(ref: str, steps: list[CopilotTaskStep]) -> Any:
    parts = ref.split(".")
    if len(parts) < 3:
        return ref
    step = next((item for item in steps if item.client_step_id == parts[1]), None)
    data: Any = step.output if step else None
    for part in parts[2:]:
        if isinstance(data, dict):
            data = data.get(part)
        elif isinstance(data, list) and part.isdigit():
            data = data[int(part)]
        else:
            return None
    return data


async def idempotency_result(db: AsyncSession, *, task: CopilotTask, step: CopilotTaskStep) -> dict[str, Any] | None:
    if step.status == "succeeded" and step.output:
        return step.output
    args = step.tool_arguments or {}
    if step.tool_name == "knowledge_bases.create" and isinstance(args.get("name"), str):
        result = await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.tenant_id == task.tenant_id,
                KnowledgeBase.status != "archived",
                func.lower(func.btrim(KnowledgeBase.name)) == args["name"].strip().lower(),
            )
        )
        kb = result.scalar_one_or_none()
        if kb:
            return {"knowledge_base": {"id": str(kb.id), "name": kb.name, "type": kb.type, "status": kb.status}}
    if step.tool_name == "agents.create_draft" and isinstance(args.get("name"), str):
        result = await db.execute(
            select(Agent).where(
                Agent.tenant_id == task.tenant_id,
                Agent.status != "archived",
                func.lower(func.btrim(Agent.name)) == args["name"].strip().lower(),
            )
        )
        agent = result.scalar_one_or_none()
        if agent:
            return {"agent": {"id": str(agent.id), "name": agent.name, "status": agent.status}}
    return None


def is_waiting_output(output: dict[str, Any]) -> bool:
    status = output.get("knowledge_base_status")
    return isinstance(status, dict) and not bool(status.get("ready"))


def mark_step_succeeded(step: CopilotTaskStep, output: dict[str, Any]) -> None:
    step.status = "succeeded"
    step.output = output
    step.error_code = None
    step.error_message = None
    step.completed_at = now()


def mark_step_waiting_external(step: CopilotTaskStep, task: CopilotTask, output: dict[str, Any]) -> None:
    interval = min(max(int(step.check_interval_seconds or 5), 5) * 2, MAX_CHECK_INTERVAL_SECONDS)
    observed = observed_status_from_output(output)
    step.status = "waiting_external"
    step.output = output
    step.last_observed_status = observed
    step.check_interval_seconds = interval
    step.next_check_at = now() + timedelta(seconds=interval)
    if step.timeout_at is None:
        timeout_seconds = int((step.wait_condition or {}).get("timeoutSeconds") or 3600)
        step.timeout_at = now() + timedelta(seconds=timeout_seconds)
    task.status = "waiting_external"


def observed_status_from_output(output: dict[str, Any]) -> str | None:
    status = output.get("knowledge_base_status")
    if isinstance(status, dict):
        if status.get("ready"):
            return "ready"
        counts = status.get("document_counts")
        if isinstance(counts, dict):
            if counts.get("failed"):
                return "failed"
            if counts.get("processing"):
                return "processing"
            if not counts.get("total"):
                return "empty"
        return str(status.get("status") or "waiting")
    return None


def claim_step(step: CopilotTaskStep, *, worker_id: str, lease_seconds: int) -> None:
    ts = now()
    step.claimed_by = worker_id
    step.claimed_at = ts
    step.heartbeat_at = ts
    step.lease_expires_at = ts + timedelta(seconds=lease_seconds)
    step.execution_attempt += 1


def release_step_lease(step: CopilotTaskStep) -> None:
    step.claimed_by = None
    step.claimed_at = None
    step.lease_expires_at = None
    step.heartbeat_at = None


def retry_delay(retry_count: int) -> timedelta:
    return timedelta(seconds=min(2 ** max(retry_count, 1) * 5, 300))


def finish_task(task: CopilotTask, steps: list[CopilotTaskStep]) -> None:
    failed = [step for step in steps if step.status == "failed"]
    succeeded = [step for step in steps if step.status == "succeeded"]
    task.status = "failed" if failed and not succeeded else "partially_succeeded" if failed else "succeeded"
    task.progress_percent = 100 if task.status in {"succeeded", "partially_succeeded"} else task.progress_percent
    task.completed_at = now()
    task.result_summary = f"已完成 {len(succeeded)} 个步骤，失败 {len(failed)} 个步骤。"


def update_progress(task: CopilotTask, steps: list[CopilotTaskStep]) -> None:
    if not steps:
        task.progress_percent = 0
        return
    done = sum(1 for step in steps if step.status in TERMINAL_STEP_STATUSES)
    task.progress_percent = int(done / len(steps) * 100)


async def write_task_audit(db: AsyncSession, *, auth: AuthContext, task: CopilotTask, action: str) -> None:
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action=action,
        resource_type="copilot_task",
        resource_id=task.id,
        detail={"task_id": str(task.id), "status": task.status},
        commit=False,
    )


def sanitize_args(args: dict[str, Any]) -> dict[str, Any]:
    sensitive = {"api_key", "password", "token", "secret", "authorization"}
    return {key: "***" if key.lower() in sensitive else value for key, value in args.items()}


def now() -> datetime:
    return datetime.now(timezone.utc)
