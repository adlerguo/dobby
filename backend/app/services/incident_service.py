from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ConversationIncident, EvalCase
from app.schemas import IncidentCreate, IncidentUpdate


async def create_incident(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    payload: IncidentCreate,
    created_by: UUID | None = None,
    commit: bool = True,
) -> ConversationIncident:
    if payload.trace_id is not None:
        existing = await find_incident_by_trace_type(
            db,
            tenant_id=tenant_id,
            trace_id=payload.trace_id,
            incident_type=payload.incident_type,
        )
        if existing is not None:
            return existing
    incident = ConversationIncident(
        tenant_id=tenant_id,
        conversation_id=payload.conversation_id,
        message_id=payload.message_id,
        agent_id=payload.agent_id,
        trace_id=payload.trace_id,
        incident_type=payload.incident_type,
        severity=payload.severity,
        status="open",
        title=payload.title,
        detail=payload.detail,
        created_by=created_by,
    )
    db.add(incident)
    try:
        await db.flush()
        if commit:
            await db.commit()
            await db.refresh(incident)
    except IntegrityError:
        await db.rollback()
        if payload.trace_id is not None:
            existing = await find_incident_by_trace_type(
                db,
                tenant_id=tenant_id,
                trace_id=payload.trace_id,
                incident_type=payload.incident_type,
            )
            if existing is not None:
                return existing
        raise
    return incident


async def create_incident_safe(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    payload: IncidentCreate,
    created_by: UUID | None = None,
) -> ConversationIncident | None:
    try:
        return await create_incident(
            db, tenant_id=tenant_id, payload=payload, created_by=created_by
        )
    except Exception:
        await db.rollback()
        return None


async def find_incident_by_trace_type(
    db: AsyncSession, *, tenant_id: UUID, trace_id: UUID, incident_type: str
) -> ConversationIncident | None:
    result = await db.execute(
        select(ConversationIncident).where(
            ConversationIncident.tenant_id == tenant_id,
            ConversationIncident.trace_id == trace_id,
            ConversationIncident.incident_type == incident_type,
        )
    )
    return result.scalar_one_or_none()


async def list_incidents(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    status: str | None = None,
    incident_type: str | None = None,
    severity: str | None = None,
    agent_id: UUID | None = None,
    limit: int = 50,
) -> list[ConversationIncident]:
    stmt = select(ConversationIncident).where(ConversationIncident.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(ConversationIncident.status == status)
    if incident_type:
        stmt = stmt.where(ConversationIncident.incident_type == incident_type)
    if severity:
        stmt = stmt.where(ConversationIncident.severity == severity)
    if agent_id:
        stmt = stmt.where(ConversationIncident.agent_id == agent_id)
    result = await db.execute(stmt.order_by(ConversationIncident.created_at.desc()).limit(limit))
    return list(result.scalars().all())


async def update_incident(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    incident_id: UUID,
    payload: IncidentUpdate,
    user_id: UUID | None,
) -> ConversationIncident | None:
    incident = await get_incident(db, tenant_id=tenant_id, incident_id=incident_id)
    if incident is None:
        return None
    values = payload.model_dump(exclude_unset=True)
    if "status" in values and values["status"] is not None:
        incident.status = values["status"]
        if incident.status in {"resolved", "ignored"}:
            incident.resolved_by = user_id
            incident.resolved_at = datetime.now(timezone.utc)
    if "resolution_note" in values:
        incident.resolution_note = values["resolution_note"]
    await db.commit()
    await db.refresh(incident)
    return incident


async def get_incident(
    db: AsyncSession, *, tenant_id: UUID, incident_id: UUID
) -> ConversationIncident | None:
    result = await db.execute(
        select(ConversationIncident).where(
            ConversationIncident.id == incident_id,
            ConversationIncident.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def incident_to_eval_case(
    db: AsyncSession, *, tenant_id: UUID, incident_id: UUID
) -> EvalCase | None:
    incident = await get_incident(db, tenant_id=tenant_id, incident_id=incident_id)
    if incident is None:
        return None
    detail = incident.detail or {}
    case = EvalCase(
        tenant_id=tenant_id,
        scene=f"incident/{incident.incident_type}",
        input=str(detail.get("query") or incident.title),
        expected=str(detail.get("expected") or ""),
        assert_type="always_pass",
        threshold=None,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return case


def incident_from_runtime(
    *,
    incident_type: str,
    severity: str,
    title: str,
    tenant_id: UUID,
    conversation_id: UUID | None,
    message_id: UUID | None,
    agent_id: UUID | None,
    trace_id: UUID | None,
    query: str | None = None,
    answer: str | None = None,
    detail: dict[str, Any] | None = None,
) -> IncidentCreate:
    payload_detail = dict(detail or {})
    if query is not None:
        payload_detail.setdefault("query", query)
    if answer is not None:
        payload_detail.setdefault("answer", answer)
    return IncidentCreate(
        conversation_id=conversation_id,
        message_id=message_id,
        agent_id=agent_id,
        trace_id=trace_id,
        incident_type=incident_type,
        severity=severity,
        title=title,
        detail=payload_detail,
    )
