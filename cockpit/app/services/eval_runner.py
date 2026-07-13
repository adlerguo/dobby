from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients.wanwu_bff import WanwuBFFClient
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.eval import EvalCase, EvalRun, EvalRunItem
from app.schemas.eval import EvalRunCreate
from app.services.eval_scoring import assess_eval_case
from app.services.sse_contract import AssistantStreamCollector


async def create_eval_run(session: AsyncSession, payload: EvalRunCreate, created_by: str) -> EvalRun:
    result = await session.execute(select(EvalCase).where(EvalCase.id.in_(payload.case_ids)))
    cases = list(result.scalars().all())
    if len(cases) != len(payload.case_ids):
        raise ValueError("eval_case_not_found")

    run = EvalRun(
        target_type=payload.target_type,
        target_id=payload.target_id,
        status="pending",
        total_cases=len(cases),
        concurrency=payload.concurrency or settings.eval_default_concurrency,
        created_by=created_by,
        run_config=payload.run_config,
    )
    session.add(run)
    await session.flush()
    for case in cases:
        session.add(EvalRunItem(run_id=run.id, case_id=case.id, status="pending"))
    await session.commit()
    run = await _load_run(session, run.id)
    if run is None:
        raise ValueError("eval_run_create_failed")

    # 阶段2先采用进程内异步任务；多副本调度和持久队列在后续阶段再收敛。
    asyncio.create_task(run_eval(run.id))
    return run


async def run_eval(run_id: UUID) -> None:
    async with AsyncSessionLocal() as session:
        run = await _load_run(session, run_id)
        if not run:
            return
        run.status = "running"
        run.started_at = datetime.now(UTC)
        await session.commit()

    semaphore = asyncio.Semaphore(max(1, settings.eval_default_concurrency))

    async with AsyncSessionLocal() as session:
        run = await _load_run(session, run_id)
        if not run:
            return
        semaphore = asyncio.Semaphore(max(1, run.concurrency))
        await asyncio.gather(*[_run_item_with_semaphore(semaphore, run_id, item.id) for item in run.items])
        await _refresh_run_summary(session, run_id)


async def _run_item_with_semaphore(semaphore: asyncio.Semaphore, run_id: UUID, item_id: UUID) -> None:
    async with semaphore:
        await _run_item(run_id, item_id)


async def _run_item(run_id: UUID, item_id: UUID) -> None:
    async with AsyncSessionLocal() as session:
        run = await _load_run(session, run_id)
        item = await session.get(EvalRunItem, item_id, options=[selectinload(EvalRunItem.case)])
        if not run or not item or not item.case:
            return
        item.status = "running"
        await session.commit()

        last_error: str | None = None
        for attempt in range(2):
            item.retry_count = attempt
            try:
                result = await _call_assistant(run.target_id, item.case.query, run.run_config.get("org_id"))
                if result.error:
                    raise RuntimeError(result.error)
                score_result = assess_eval_case(
                    answer=result.answer,
                    expected_answer=item.case.expected_answer,
                    expected_keywords=item.case.expected_keywords,
                    scoring_config=item.case.scoring_config,
                    latency_ms=result.total_latency_ms,
                )
                item.status = "completed"
                item.answer = result.answer
                item.score = Decimal(str(round(score_result.score, 2)))
                item.passed = score_result.passed
                item.failure_reason = score_result.reason
                item.first_frame_latency_ms = result.first_frame_latency_ms
                item.total_latency_ms = result.total_latency_ms
                item.frame_count = result.frame_count
                item.conversation_id = result.conversation_id
                item.raw_response = {
                    "frames": result.raw_frames,
                    "terminal_frame": result.terminal_frame,
                    "usage": result.usage,
                }
                await session.commit()
                return
            except NotImplementedError as exc:
                last_error = str(exc)
                break
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                if attempt == 0:
                    continue

        item.status = "failed"
        item.passed = False
        item.failure_reason = last_error or "eval_item_failed"
        item.raw_response = {"error": item.failure_reason}
        await session.commit()


async def _call_assistant(assistant_id: str, prompt: str, org_id: str | None):
    collector = AssistantStreamCollector()
    client = WanwuBFFClient()
    async for data in client.stream_draft_assistant(
        assistant_id=assistant_id,
        prompt=prompt,
        org_id=org_id,
        timeout_seconds=settings.eval_timeout_seconds,
    ):
        collector.feed_sse_data(data)
    return collector.result()


async def _load_run(session: AsyncSession, run_id: UUID) -> EvalRun | None:
    return await session.get(EvalRun, run_id, options=[selectinload(EvalRun.items)])


async def _refresh_run_summary(session: AsyncSession, run_id: UUID) -> None:
    run = await _load_run(session, run_id)
    if not run:
        return
    completed = [item for item in run.items if item.status in {"completed", "failed"}]
    failed_items = [item for item in run.items if item.status == "failed"]
    run.completed_cases = len(completed)
    run.passed_cases = len([item for item in run.items if item.passed is True])
    run.failed_cases = len([item for item in run.items if item.passed is False or item.status == "failed"])
    run.finished_at = datetime.now(UTC)
    if failed_items:
        run.status = "failed"
        run.error_message = failed_items[0].failure_reason
    else:
        run.status = "completed"
        run.error_message = None
    await session.commit()
