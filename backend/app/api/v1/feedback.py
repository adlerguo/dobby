from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, get_current_auth, require_perm
from app.core.database import get_db
from app.schemas import EvalCaseOut, ExperienceOut, FeedbackCreate, FeedbackOut
from app.services.audit_service import write_audit
from app.services.feedback_service import (
    create_message_feedback,
    feedback_to_eval_case,
    feedback_to_experience,
    list_feedback,
)

router = APIRouter(tags=["feedback"])


@router.post(
    "/messages/{message_id}/feedback",
    response_model=FeedbackOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create message feedback",
)
async def create_message_feedback_api(
    message_id: UUID,
    payload: FeedbackCreate,
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
):
    try:
        feedback = await create_message_feedback(
            db,
            tenant_id=auth.tenant_id,
            message_id=message_id,
            payload=payload,
            user_id=auth.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if feedback is None:
        raise HTTPException(status_code=404, detail="message_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="message.feedback.create",
        resource_type="message",
        resource_id=message_id,
        detail={"rating": feedback.rating, "reason": feedback.reason},
        request=request,
    )
    return feedback


@router.get("/feedback", response_model=list[FeedbackOut], summary="List feedback")
async def list_feedback_api(
    agent_id: UUID | None = Query(default=None),
    rating: str | None = Query(default=None),
    reason: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
):
    return await list_feedback(
        db,
        tenant_id=auth.tenant_id,
        agent_id=agent_id,
        rating=rating,
        reason=reason,
        limit=limit,
    )


@router.post(
    "/feedback/{feedback_id}/to-eval-case",
    response_model=EvalCaseOut,
    status_code=status.HTTP_201_CREATED,
    summary="Convert feedback to eval case",
)
async def feedback_to_eval_case_api(
    feedback_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
):
    case = await feedback_to_eval_case(
        db, tenant_id=auth.tenant_id, feedback_id=feedback_id
    )
    if case is None:
        raise HTTPException(status_code=404, detail="feedback_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="message.feedback.to_eval_case",
        resource_type="feedback",
        resource_id=feedback_id,
        detail={"case_id": str(case.id)},
        request=request,
    )
    return case


@router.post(
    "/feedback/{feedback_id}/to-experience",
    response_model=ExperienceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Convert positive feedback to experience",
)
async def feedback_to_experience_api(
    feedback_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
):
    try:
        experience = await feedback_to_experience(
            db, tenant_id=auth.tenant_id, feedback_id=feedback_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if experience is None:
        raise HTTPException(status_code=404, detail="feedback_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="message.feedback.to_experience",
        resource_type="feedback",
        resource_id=feedback_id,
        detail={"experience_id": str(experience.id)},
        request=request,
    )
    return experience
