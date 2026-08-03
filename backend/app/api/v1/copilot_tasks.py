import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, get_current_auth
from app.core.database import get_db
from app.schemas.copilot_task import (
    CopilotTaskActionIn,
    CopilotTaskCreate,
    CopilotTaskOut,
    CopilotTaskPlan,
    CopilotTaskPlanRequest,
)
from app.services.copilot_planner import plan_copilot_task
from app.services.copilot_task_events import list_task_events
from app.services.copilot_task_service import (
    cancel_copilot_task,
    confirm_copilot_task,
    create_copilot_task,
    get_copilot_task_out,
    list_copilot_tasks,
    pause_copilot_task,
    resume_copilot_task,
    retry_copilot_task,
)

router = APIRouter(prefix="/copilot/tasks", tags=["copilot-tasks"])


@router.post("/plan", response_model=CopilotTaskPlan, summary="Plan copilot task")
async def plan_copilot_task_api(
    payload: CopilotTaskPlanRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> CopilotTaskPlan:
    return await plan_copilot_task(
        db,
        auth=auth,
        goal=payload.goal,
        workspace_id=payload.workspace_id,
        conversation_id=payload.conversation_id,
    )


@router.post("", response_model=CopilotTaskOut, summary="Create copilot task")
async def create_copilot_task_api(
    payload: CopilotTaskCreate,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> CopilotTaskOut:
    return await create_copilot_task(db, auth=auth, payload=payload)


@router.get("", response_model=list[CopilotTaskOut], summary="List copilot tasks")
async def list_copilot_task_api(
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> list[CopilotTaskOut]:
    return await list_copilot_tasks(db, auth=auth, status=status, limit=limit)


@router.get("/{task_id}", response_model=CopilotTaskOut, summary="Get copilot task")
async def get_copilot_task_api(
    task_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> CopilotTaskOut:
    return await get_copilot_task_out(db, auth=auth, task_id=task_id)


@router.post("/{task_id}/confirm", response_model=CopilotTaskOut, summary="Confirm and run copilot task")
async def confirm_copilot_task_api(
    task_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> CopilotTaskOut:
    return await confirm_copilot_task(db, auth=auth, task_id=task_id)


@router.post("/{task_id}/pause", response_model=CopilotTaskOut, summary="Pause copilot task")
async def pause_copilot_task_api(
    task_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> CopilotTaskOut:
    return await pause_copilot_task(db, auth=auth, task_id=task_id)


@router.post("/{task_id}/resume", response_model=CopilotTaskOut, summary="Resume copilot task")
async def resume_copilot_task_api(
    task_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> CopilotTaskOut:
    return await resume_copilot_task(db, auth=auth, task_id=task_id)


@router.post("/{task_id}/cancel", response_model=CopilotTaskOut, summary="Cancel copilot task")
async def cancel_copilot_task_api(
    task_id: UUID,
    payload: CopilotTaskActionIn,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> CopilotTaskOut:
    return await cancel_copilot_task(db, auth=auth, task_id=task_id, reason=payload.reason)


@router.post("/{task_id}/retry", response_model=CopilotTaskOut, summary="Retry failed copilot task")
async def retry_copilot_task_api(
    task_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> CopilotTaskOut:
    return await retry_copilot_task(db, auth=auth, task_id=task_id)


@router.get("/{task_id}/events", summary="Stream copilot task events")
async def stream_copilot_task_events(
    task_id: UUID,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    async def events():
        cursor = parse_last_event_id(last_event_id)
        idle_ticks = 0
        while idle_ticks < 300:
            task = await get_copilot_task_out(db, auth=auth, task_id=task_id)
            task_events = await list_task_events(db, task=await get_task_model_for_events(db, auth, task_id), after_event_id=cursor)
            if task_events:
                idle_ticks = 0
                for item in task_events:
                    cursor = item.event_id
                    yield f"id: {item.event_id}\n"
                    yield f"event: {item.event_type}\n"
                    yield f"data: {json.dumps(item.payload, ensure_ascii=False, default=str)}\n\n"
            else:
                idle_ticks += 1
                yield f"event: heartbeat\n"
                yield f"data: {json.dumps({'task_id': str(task.id), 'status': task.status}, ensure_ascii=False)}\n\n"
            if task.status in {"succeeded", "partially_succeeded", "failed", "cancelled"} and not task_events:
                break
            await asyncio.sleep(2)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def get_task_model_for_events(db: AsyncSession, auth: AuthContext, task_id: UUID):
    from app.services.copilot_task_service import get_owned_task

    return await get_owned_task(db, auth=auth, task_id=task_id)


def parse_last_event_id(raw: str | None) -> int:
    try:
        return max(int(raw or 0), 0)
    except ValueError:
        return 0
