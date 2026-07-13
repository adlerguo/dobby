import json
from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, get_current_auth
from app.core.database import SessionLocal, get_db
from app.models import Conversation, Message
from app.orchestrator import stream_agent_events as run_stream_agent_events
from app.schemas import AgentRunIn, ChatIn, ConversationOut, MessageOut

router = APIRouter(tags=["chat"])


@router.post("/chat", summary="Stream chat with an agent")
async def chat_stream(
    payload: ChatIn,
    auth: AuthContext = Depends(get_current_auth),
) -> StreamingResponse:
    return StreamingResponse(
        stream_chat_events(auth=auth, payload=payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations", response_model=list[ConversationOut], summary="List conversations")
async def list_conversations(
    agent_id: UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> list:
    stmt = (
        select(Conversation)
        .where(Conversation.tenant_id == auth.tenant_id)
        .order_by(Conversation.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if agent_id is not None:
        stmt = stmt.where(Conversation.agent_id == agent_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/conversations/{conversation_id}", response_model=ConversationOut, summary="Get conversation")
async def get_conversation(
    conversation_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> Conversation:
    conversation = await load_conversation(db, tenant_id=auth.tenant_id, conversation_id=conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation_not_found")
    return conversation


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[MessageOut],
    summary="List conversation messages",
)
async def list_conversation_messages(
    conversation_id: UUID,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> list:
    conversation = await load_conversation(db, tenant_id=auth.tenant_id, conversation_id=conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation_not_found")

    result = await db.execute(
        select(Message)
        .where(Message.tenant_id == auth.tenant_id, Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())


async def stream_chat_events(auth: AuthContext, payload: ChatIn) -> AsyncGenerator[str, None]:
    async with SessionLocal() as db:
        try:
            async for event in run_stream_agent_events(
                db,
                tenant_id=auth.tenant_id,
                user_id=auth.user_id,
                agent_id=payload.agent_id,
                payload=AgentRunIn(
                    query=payload.query,
                    conversation_id=payload.conversation_id,
                    workspace_id=payload.workspace_id,
                    max_tokens=payload.max_tokens,
                    history_limit=payload.history_limit,
                    top_k=payload.top_k,
                    score_threshold=payload.score_threshold,
                    match_type=payload.match_type,
                    max_tool_rounds=payload.max_tool_rounds,
                    tool_calls=payload.tool_calls,
                ),
            ):
                yield sse_event(event["event"], event["data"])
        except ValueError as exc:
            yield sse_event("error", {"detail": str(exc)})
            return


async def load_conversation(db: AsyncSession, *, tenant_id: UUID, conversation_id: UUID) -> Conversation | None:
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id, Conversation.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

