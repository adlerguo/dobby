from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Conversation,
    EvalCase,
    Experience,
    Message,
    MessageFeedback,
    RunTrace,
)
from app.schemas import FeedbackCreate
from app.services.incident_service import create_incident, incident_from_runtime


async def create_message_feedback(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    message_id: UUID,
    payload: FeedbackCreate,
    user_id: UUID | None,
) -> MessageFeedback | None:
    message = await db.get(Message, message_id)
    if message is None or message.tenant_id != tenant_id:
        return None
    if message.role != "assistant":
        raise ValueError("feedback_assistant_message_required")
    conversation = None
    if message.conversation_id is not None:
        conversation = await db.get(Conversation, message.conversation_id)
    trace = await latest_root_trace(
        db, tenant_id=tenant_id, conversation_id=message.conversation_id
    )
    feedback = MessageFeedback(
        tenant_id=tenant_id,
        message_id=message.id,
        conversation_id=message.conversation_id,
        agent_id=conversation.agent_id if conversation else None,
        trace_id=trace.id if trace else None,
        rating=payload.rating,
        reason=payload.reason,
        comment=payload.comment,
        citations=message.citations or [],
        meta=payload.meta,
        created_by=user_id,
    )
    db.add(feedback)
    await db.flush()
    if payload.rating == "negative":
        await create_incident(
            db,
            tenant_id=tenant_id,
            payload=incident_from_runtime(
                tenant_id=tenant_id,
                conversation_id=message.conversation_id,
                message_id=message.id,
                agent_id=feedback.agent_id,
                trace_id=feedback.trace_id,
                incident_type="negative_feedback",
                severity="medium",
                title=f"用户点踩：{payload.reason or 'other'}",
                answer=message.content,
                detail={
                    "reason": payload.reason,
                    "comment": payload.comment,
                    "citations": message.citations or [],
                    "feedback_id": str(feedback.id),
                },
            ),
            created_by=user_id,
            commit=False,
        )
    await db.commit()
    await db.refresh(feedback)
    return feedback


async def latest_root_trace(
    db: AsyncSession, *, tenant_id: UUID, conversation_id: UUID | None
) -> RunTrace | None:
    if conversation_id is None:
        return None
    result = await db.execute(
        select(RunTrace)
        .where(
            RunTrace.tenant_id == tenant_id,
            RunTrace.conversation_id == conversation_id,
            RunTrace.parent_id.is_(None),
        )
        .order_by(RunTrace.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_feedback(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID | None = None,
    rating: str | None = None,
    reason: str | None = None,
    limit: int = 50,
) -> list[MessageFeedback]:
    stmt = select(MessageFeedback).where(MessageFeedback.tenant_id == tenant_id)
    if agent_id:
        stmt = stmt.where(MessageFeedback.agent_id == agent_id)
    if rating:
        stmt = stmt.where(MessageFeedback.rating == rating)
    if reason:
        stmt = stmt.where(MessageFeedback.reason == reason)
    result = await db.execute(stmt.order_by(MessageFeedback.created_at.desc()).limit(limit))
    return list(result.scalars().all())


async def feedback_to_eval_case(
    db: AsyncSession, *, tenant_id: UUID, feedback_id: UUID
) -> EvalCase | None:
    feedback = await get_feedback(db, tenant_id=tenant_id, feedback_id=feedback_id)
    if feedback is None:
        return None
    message = await db.get(Message, feedback.message_id)
    query = await previous_user_message(db, tenant_id=tenant_id, message=message)
    case = EvalCase(
        tenant_id=tenant_id,
        scene=f"feedback/{feedback.reason or feedback.rating}",
        input=query.content if query else "用户反馈问题",
        expected=message.content if message else "",
        assert_type="always_pass",
        threshold=None,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return case


async def feedback_to_experience(
    db: AsyncSession, *, tenant_id: UUID, feedback_id: UUID
) -> Experience | None:
    feedback = await get_feedback(db, tenant_id=tenant_id, feedback_id=feedback_id)
    if feedback is None:
        return None
    if feedback.rating != "positive":
        raise ValueError("positive_feedback_required")
    message = await db.get(Message, feedback.message_id)
    query = await previous_user_message(db, tenant_id=tenant_id, message=message)
    experience = Experience(
        tenant_id=tenant_id,
        agent_id=feedback.agent_id,
        scene=f"feedback/{feedback.reason or 'positive'}",
        content=f"问题：{query.content if query else ''}\n答案：{message.content if message else ''}",
        embedding=None,
        meta={"source": "feedback", "feedback_id": str(feedback.id)},
    )
    db.add(experience)
    await db.commit()
    await db.refresh(experience)
    return experience


async def get_feedback(
    db: AsyncSession, *, tenant_id: UUID, feedback_id: UUID
) -> MessageFeedback | None:
    result = await db.execute(
        select(MessageFeedback).where(
            MessageFeedback.id == feedback_id,
            MessageFeedback.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def previous_user_message(
    db: AsyncSession, *, tenant_id: UUID, message: Message | None
) -> Message | None:
    if message is None or message.conversation_id is None:
        return None
    result = await db.execute(
        select(Message)
        .where(
            Message.tenant_id == tenant_id,
            Message.conversation_id == message.conversation_id,
            Message.role == "user",
            Message.created_at <= message.created_at,
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
