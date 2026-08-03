import json
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.maas_auth import maas_service_headers
from app.models import Agent, Conversation, Message, Model, RunTrace, Tool
from app.orchestrator.context import build_agent_context, estimate_tokens
from app.orchestrator.intent import classify_intent
from app.orchestrator.runtime_fallback import (
    FallbackResult,
    fallback_config,
    fallback_for_citations,
    fallback_for_intent,
    fallback_for_tool_failure,
    make_fallback,
    no_fallback,
)
from app.repositories import AgentRepository, ToolRepository
from app.schemas import (
    AgentRunIn,
    AgentRunOut,
    ContextBuildOut,
    ContextMessageOut,
    RuntimeToolCallIn,
    RuntimeToolCallOut,
)
from app.services import run_tool
from app.services.incident_service import create_incident_safe, incident_from_runtime
from app.services.workspace_service import get_workspace_resource_ids, load_workspace


@dataclass
class OrchestratorError(ValueError):
    code: str
    message: str | None = None

    def __str__(self) -> str:
        return self.code

    @property
    def detail(self) -> str:
        return self.message or self.code

    def event_data(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


async def dispatch_single_agent(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    agent_id: UUID,
    payload: AgentRunIn,
) -> AgentRunOut | None:
    return await run_agent(
        db, tenant_id=tenant_id, user_id=user_id, agent_id=agent_id, payload=payload
    )


async def run_agent(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    agent_id: UUID,
    payload: AgentRunIn,
) -> AgentRunOut | None:
    repo = AgentRepository(db, tenant_id)
    agent = await repo.get_by_id(agent_id)
    if agent is None:
        return None
    agent = agent_from_runtime_snapshot(agent, payload.runtime_snapshot)
    if agent.status != "active":
        return None

    conversation = await ensure_conversation(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        agent=agent,
        conversation_id=payload.conversation_id,
        workspace_id=payload.workspace_id,
        title=payload.query,
    )
    intent = await classify_intent(
        payload.query,
        agent.config or {},
        request_mode=payload.intent_mode,
        skip_intent=payload.skip_intent,
    )
    fallback_options = fallback_config(agent.config or {})
    intent_fallback = fallback_for_intent(intent, fallback_options)
    if intent_fallback.applied:
        context = empty_context(agent, conversation, payload.query, intent.as_dict())
        return await persist_fallback_run(
            db,
            tenant_id=tenant_id,
            conversation=conversation,
            agent=agent,
            query=payload.query,
            context=context,
            fallback=intent_fallback,
            trace_name="run_agent",
            user_id=user_id,
        )

    model = await load_llm_model(
        db, tenant_id=tenant_id, agent=agent, workspace_id=conversation.workspace_id
    )
    context = await build_agent_context(
        db,
        tenant_id=tenant_id,
        agent_id=agent.id,
        query=payload.query,
        conversation_id=conversation.id,
        workspace_id=conversation.workspace_id,
        max_tokens=payload.max_tokens,
        history_limit=payload.history_limit,
        top_k=payload.top_k,
        score_threshold=payload.score_threshold,
        match_type=payload.match_type,
        rerank_mode=payload.rerank_mode,
        intent=intent.as_dict(),
        runtime_snapshot=payload.runtime_snapshot,
    )
    if context is None:
        return None
    citation_fallback = fallback_for_citations(len(context.citations), fallback_options)
    if citation_fallback.applied:
        return await persist_fallback_run(
            db,
            tenant_id=tenant_id,
            conversation=conversation,
            agent=agent,
            query=payload.query,
            context=context,
            fallback=citation_fallback,
            trace_name="run_agent",
            user_id=user_id,
        )

    user_message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        role="user",
        content=payload.query,
        tokens=estimate_tokens(payload.query),
        citations=[],
    )
    db.add(user_message)
    await db.flush()

    root_trace = RunTrace(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        agent_id=agent.id,
        span_type="agent",
        name="run_agent",
        status="running",
        input={
            "query": payload.query,
            "workspace_id": str(conversation.workspace_id)
            if conversation.workspace_id
            else None,
            "model": model.name,
                "context": {
                "token_budget": context.token_budget,
                "truncation": context.truncation,
                "tool_count": len(context.tools),
                "citation_count": len(context.citations),
                    "rerank": context_rerank_summary(context),
                    "compression": context_compression_summary(context),
                },
                "intent": intent.as_dict(),
            },
        output={},
        tokens=0,
        latency_ms=0,
    )
    db.add(root_trace)
    await db.flush()

    started = time.perf_counter()
    try:
        messages = [
            {"role": message.role, "content": message.content}
            for message in context.messages
        ]
        first_response = await call_maas_chat(
            db,
            tenant_id,
            conversation.id,
            agent.id,
            root_trace.id,
            model.name,
            agent,
            messages,
        )
        first_answer = extract_answer(first_response)
        requested_tool_calls = payload.tool_calls or auto_tool_calls(
            agent, context, payload.query
        )

        tool_results = await run_tool_loop(
            db,
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            agent=agent,
            parent_trace_id=root_trace.id,
            context=context,
            assistant_text=first_answer,
            requested_tool_calls=requested_tool_calls,
            max_tool_rounds=payload.max_tool_rounds,
        )

        final_response = first_response
        answer = first_answer
        tool_failed = any(result.status == "failed" for result in tool_results)
        if tool_results and not tool_failed:
            messages.append({"role": "assistant", "content": first_answer})
            messages.append(
                {"role": "user", "content": tool_result_prompt(tool_results)}
            )
            final_response = await call_maas_chat(
                db,
                tenant_id,
                conversation.id,
                agent.id,
                root_trace.id,
                model.name,
                agent,
                messages,
                name="maas_final",
            )
            answer = extract_answer(final_response)
            if agent.type == "nl2data":
                answer = format_nl2data_answer(tool_results)
        elif tool_failed:
            tool_fallback = fallback_for_tool_failure(tool_results, fallback_options)
            answer = tool_fallback.message or format_tool_failure_answer(tool_results)

        usage = final_response.get("usage") or {}
        assistant_message = Message(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="assistant",
            content=answer,
            tokens=estimate_tokens(answer),
            citations=[
                citation.model_dump(mode="json") for citation in context.citations
            ],
        )
        db.add(assistant_message)
        active_fallback = (
            fallback_for_tool_failure(tool_results, fallback_options)
            if tool_failed
            else no_fallback()
        )
        root_trace.status = "failed" if tool_failed else "ok"
        root_trace.output = {
            "answer": answer,
            "usage": usage,
            "tool_results": [result.model_dump(mode="json") for result in tool_results],
            "citations": [
                citation.model_dump(mode="json") for citation in context.citations
            ],
            "intent": intent.as_dict(),
            "compression": context_compression_summary(context),
            "fallback": active_fallback.as_dict(),
        }
        root_trace.tokens = int(
            (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
        )
        root_trace.latency_ms = int((time.perf_counter() - started) * 1000)
        await db.flush()
        await db.commit()
        await db.refresh(user_message)
        await db.refresh(assistant_message)
        await db.refresh(root_trace)
        await archive_runtime_incidents(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation=conversation,
            agent=agent,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            trace_id=root_trace.id,
            query=payload.query,
            answer=answer,
            fallback=active_fallback,
            tool_results=tool_results,
            citations=context.citations,
        )

        return AgentRunOut(
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            trace_id=root_trace.id,
            answer=answer,
            citations=context.citations,
            tool_results=tool_results,
            usage=usage,
            context=context,
            intent=intent.as_dict(),
            fallback_applied=active_fallback.applied,
            fallback_reason=active_fallback.reason,
            fallback_message=active_fallback.message,
        )
    except Exception as exc:
        fallback = make_fallback(
            "model_error",
            fallback_options,
            detail={"error": str(exc) or exc.__class__.__name__},
        )
        if fallback.applied:
            await commit_fallback_root_trace(
                db,
                root_trace=root_trace,
                started=started,
                context=context,
                intent=intent.as_dict(),
                fallback=fallback,
                usage={},
                tool_results=[],
            )
            assistant_message = Message(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                role="assistant",
                content=fallback.message or "",
                tokens=estimate_tokens(fallback.message or ""),
                citations=[],
            )
            db.add(assistant_message)
            await db.flush()
            await db.commit()
            await db.refresh(user_message)
            await db.refresh(assistant_message)
            await db.refresh(root_trace)
            await archive_runtime_incidents(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                conversation=conversation,
                agent=agent,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
                trace_id=root_trace.id,
                query=payload.query,
                answer=fallback.message or "",
                fallback=fallback,
                tool_results=[],
                citations=[],
            )
            return AgentRunOut(
                conversation_id=conversation.id,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
                trace_id=root_trace.id,
                answer=fallback.message or "",
                citations=[],
                tool_results=[],
                usage={},
                context=context,
                intent=intent.as_dict(),
                fallback_applied=True,
                fallback_reason=fallback.reason,
                fallback_message=fallback.message,
            )
        error = runtime_error(exc)
        await commit_failed_root_trace(
            db, root_trace=root_trace, started=started, error=error
        )
        raise error from exc


async def stream_agent_events(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    agent_id: UUID,
    payload: AgentRunIn,
) -> AsyncGenerator[dict[str, Any], None]:
    repo = AgentRepository(db, tenant_id)
    agent = await repo.get_by_id(agent_id)
    if agent is None:
        yield {
            "event": "error",
            "data": OrchestratorError("agent_not_found").event_data(),
        }
        return
    agent = agent_from_runtime_snapshot(agent, payload.runtime_snapshot)
    if agent.status != "active":
        yield {
            "event": "error",
            "data": OrchestratorError("agent_not_found").event_data(),
        }
        return

    conversation = await ensure_conversation(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        agent=agent,
        conversation_id=payload.conversation_id,
        workspace_id=payload.workspace_id,
        title=payload.query,
    )
    intent = await classify_intent(
        payload.query,
        agent.config or {},
        request_mode=payload.intent_mode,
        skip_intent=payload.skip_intent,
    )
    fallback_options = fallback_config(agent.config or {})
    intent_fallback = fallback_for_intent(intent, fallback_options)
    if intent_fallback.applied:
        context = empty_context(agent, conversation, payload.query, intent.as_dict())
        result = await persist_fallback_run(
            db,
            tenant_id=tenant_id,
            conversation=conversation,
            agent=agent,
            query=payload.query,
            context=context,
            fallback=intent_fallback,
            trace_name="stream_agent",
            user_id=user_id,
        )
        yield {"event": "fallback", "data": intent_fallback.as_dict()}
        yield {"event": "delta", "data": {"text": result.answer}}
        yield {"event": "done", "data": stream_done_payload(result)}
        return

    model = await load_llm_model(
        db, tenant_id=tenant_id, agent=agent, workspace_id=conversation.workspace_id
    )
    context = await build_agent_context(
        db,
        tenant_id=tenant_id,
        agent_id=agent.id,
        query=payload.query,
        conversation_id=conversation.id,
        workspace_id=conversation.workspace_id,
        max_tokens=payload.max_tokens,
        history_limit=payload.history_limit,
        top_k=payload.top_k,
        score_threshold=payload.score_threshold,
        match_type=payload.match_type,
        rerank_mode=payload.rerank_mode,
        intent=intent.as_dict(),
        runtime_snapshot=payload.runtime_snapshot,
    )
    if context is None:
        yield {
            "event": "error",
            "data": OrchestratorError("agent_not_found").event_data(),
        }
        return
    citation_fallback = fallback_for_citations(len(context.citations), fallback_options)
    if citation_fallback.applied:
        result = await persist_fallback_run(
            db,
            tenant_id=tenant_id,
            conversation=conversation,
            agent=agent,
            query=payload.query,
            context=context,
            fallback=citation_fallback,
            trace_name="stream_agent",
            user_id=user_id,
        )
        yield {"event": "fallback", "data": citation_fallback.as_dict()}
        yield {"event": "delta", "data": {"text": result.answer}}
        yield {"event": "done", "data": stream_done_payload(result)}
        return

    user_message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        role="user",
        content=payload.query,
        tokens=estimate_tokens(payload.query),
        citations=[],
    )
    db.add(user_message)
    await db.flush()

    root_trace = RunTrace(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        agent_id=agent.id,
        span_type="agent",
        name="stream_agent",
        status="running",
        input={
            "query": payload.query,
            "workspace_id": str(conversation.workspace_id)
            if conversation.workspace_id
            else None,
            "model": model.name,
                "context": {
                "token_budget": context.token_budget,
                "truncation": context.truncation,
                "tool_count": len(context.tools),
                "citation_count": len(context.citations),
                    "rerank": context_rerank_summary(context),
                    "compression": context_compression_summary(context),
                },
                "intent": intent.as_dict(),
            },
        output={},
        tokens=0,
        latency_ms=0,
    )
    db.add(root_trace)
    await db.flush()

    started = time.perf_counter()
    messages = [
        {"role": message.role, "content": message.content}
        for message in context.messages
    ]
    answer_parts: list[str] = []
    usage: dict[str, Any] = {}
    citations_sent = False
    try:
        async for event in call_maas_chat_stream(
            db,
            tenant_id,
            conversation.id,
            agent.id,
            root_trace.id,
            model.name,
            agent,
            messages,
        ):
            if event["type"] == "delta":
                if not citations_sent:
                    for citation in context.citations:
                        yield {
                            "event": "citation",
                            "data": citation.model_dump(mode="json"),
                        }
                    citations_sent = True
                text = event["text"]
                answer_parts.append(text)
                yield {"event": "delta", "data": {"text": text}}
            elif event["type"] == "usage":
                usage = event["usage"]
    except Exception as exc:
        fallback = make_fallback(
            "model_error",
            fallback_options,
            detail={"error": str(exc) or exc.__class__.__name__},
        )
        await commit_fallback_root_trace(
            db,
            root_trace=root_trace,
            started=started,
            context=context,
            intent=intent.as_dict(),
            fallback=fallback,
            usage=usage,
            tool_results=[],
        )
        assistant_message = Message(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="assistant",
            content=fallback.message or "",
            tokens=estimate_tokens(fallback.message or ""),
            citations=[],
        )
        db.add(assistant_message)
        await db.flush()
        await db.commit()
        await db.refresh(assistant_message)
        await db.refresh(root_trace)
        await archive_runtime_incidents(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation=conversation,
            agent=agent,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            trace_id=root_trace.id,
            query=payload.query,
            answer=fallback.message or "",
            fallback=fallback,
            tool_results=[],
            citations=context.citations,
        )
        yield {"event": "fallback", "data": fallback.as_dict()}
        yield {"event": "delta", "data": {"text": fallback.message or ""}}
        yield {
            "event": "done",
            "data": {
                "conversation_id": str(conversation.id),
                "user_message_id": str(user_message.id),
                "assistant_message_id": str(assistant_message.id),
                "trace_id": str(root_trace.id),
                "usage": usage,
                "tool_results": [],
                "citation_count": len(context.citations),
                "status": "fallback",
                "intent": intent.as_dict(),
                "compression_strategy": context.compression_strategy,
                "compression_applied": context.compression_applied,
                "original_history_tokens": context.original_history_tokens,
                "compressed_history_tokens": context.compressed_history_tokens,
                "compressed_message_count": context.compressed_message_count,
                "compression_fallback": context.compression_fallback,
                **fallback.as_dict(),
            },
        }
        return

    if not citations_sent:
        for citation in context.citations:
            yield {"event": "citation", "data": citation.model_dump(mode="json")}
        citations_sent = True

    tool_results: list[RuntimeToolCallOut] = []
    try:
        answer = "".join(answer_parts)
        tool_results = await run_tool_loop(
            db,
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            agent=agent,
            parent_trace_id=root_trace.id,
            context=context,
            assistant_text=answer,
            requested_tool_calls=payload.tool_calls
            or auto_tool_calls(agent, context, payload.query),
            max_tool_rounds=payload.max_tool_rounds,
        )
        execution_error = tool_exception_error(tool_results)
        if execution_error is not None:
            await commit_failed_root_trace(
                db,
                root_trace=root_trace,
                started=started,
                error=execution_error,
                usage=usage,
                tool_results=tool_results,
                citations=context.citations,
            )
            yield {"event": "error", "data": execution_error.event_data()}
            yield {
                "event": "done",
                "data": {
                    "conversation_id": str(conversation.id),
                    "trace_id": str(root_trace.id),
                    "usage": usage,
                    "tool_results": [
                        tool.model_dump(mode="json") for tool in tool_results
                    ],
                    "citation_count": len(context.citations),
                    "status": "failed",
                },
            }
            return

        tool_failed = any(result.status == "failed" for result in tool_results)
        if tool_results and not tool_failed:
            final_messages = [
                *messages,
                {"role": "assistant", "content": answer},
                {"role": "user", "content": tool_result_prompt(tool_results)},
            ]
            final_response = await call_maas_chat(
                db,
                tenant_id,
                conversation.id,
                agent.id,
                root_trace.id,
                model.name,
                agent,
                final_messages,
                name="maas_final",
            )
            answer = extract_answer(final_response)
            usage = final_response.get("usage") or usage
            yield {"event": "delta", "data": {"text": "\n\n" + answer}}
        elif tool_failed:
            tool_fallback = fallback_for_tool_failure(tool_results, fallback_options)
            tool_error_answer = tool_fallback.message or format_tool_failure_answer(tool_results)
            answer = (
                answer + "\n\n" + tool_error_answer if answer else tool_error_answer
            )
            yield {"event": "fallback", "data": tool_fallback.as_dict()}
            yield {"event": "delta", "data": {"text": "\n\n" + tool_error_answer}}
    except Exception as exc:
        error = runtime_error(exc)
        await commit_failed_root_trace(
            db,
            root_trace=root_trace,
            started=started,
            error=error,
            usage=usage,
            tool_results=tool_results,
            citations=context.citations,
        )
        yield {"event": "error", "data": error.event_data()}
        yield {
            "event": "done",
            "data": {
                "conversation_id": str(conversation.id),
                "trace_id": str(root_trace.id),
                "usage": usage,
                "tool_results": [tool.model_dump(mode="json") for tool in tool_results],
                "citation_count": len(context.citations),
                "status": "failed",
            },
        }
        return

    assistant_message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        role="assistant",
        content=answer,
        tokens=estimate_tokens(answer),
        citations=[citation.model_dump(mode="json") for citation in context.citations],
    )
    db.add(assistant_message)
    active_fallback = (
        fallback_for_tool_failure(tool_results, fallback_options)
        if tool_failed
        else no_fallback()
    )
    root_trace.status = "failed" if tool_failed else "ok"
    root_trace.output = {
        "answer": answer,
        "usage": usage,
        "tool_results": [result.model_dump(mode="json") for result in tool_results],
        "citations": [
            citation.model_dump(mode="json") for citation in context.citations
        ],
        "intent": intent.as_dict(),
        "compression": context_compression_summary(context),
        "fallback": active_fallback.as_dict(),
    }
    root_trace.tokens = int(
        (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
    )
    root_trace.latency_ms = int((time.perf_counter() - started) * 1000)
    await db.flush()
    await db.commit()
    await db.refresh(user_message)
    await db.refresh(assistant_message)
    await db.refresh(root_trace)
    await archive_runtime_incidents(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation=conversation,
        agent=agent,
        user_message_id=user_message.id,
        assistant_message_id=assistant_message.id,
        trace_id=root_trace.id,
        query=payload.query,
        answer=answer,
        fallback=active_fallback,
        tool_results=tool_results,
        citations=context.citations,
    )
    yield {
        "event": "done",
        "data": {
            "conversation_id": str(conversation.id),
            "user_message_id": str(user_message.id),
            "assistant_message_id": str(assistant_message.id),
            "trace_id": str(root_trace.id),
            "usage": usage,
            "tool_results": [tool.model_dump(mode="json") for tool in tool_results],
            "citation_count": len(context.citations),
            "intent": intent.as_dict(),
            "compression_strategy": context.compression_strategy,
            "compression_applied": context.compression_applied,
            "original_history_tokens": context.original_history_tokens,
            "compressed_history_tokens": context.compressed_history_tokens,
            "compressed_message_count": context.compressed_message_count,
            "compression_fallback": context.compression_fallback,
            **active_fallback.as_dict(),
        },
    }


def agent_from_runtime_snapshot(agent: Agent, snapshot: dict[str, Any] | None):
    if not snapshot:
        return agent
    snapshot_agent = snapshot.get("agent")
    if not isinstance(snapshot_agent, dict):
        return agent
    model_id = parse_uuid(snapshot_agent.get("model_id")) or agent.model_id
    return SimpleNamespace(
        id=agent.id,
        tenant_id=agent.tenant_id,
        status="active",
        name=snapshot_agent.get("name") or agent.name,
        type=snapshot_agent.get("type") or agent.type,
        persona=snapshot_agent.get("persona"),
        config=snapshot_agent.get("config")
        if isinstance(snapshot_agent.get("config"), dict)
        else {},
        model_id=model_id,
    )


def parse_uuid(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


async def load_llm_model(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    agent: Agent,
    workspace_id: UUID | None,
) -> Model:
    if workspace_id is not None:
        workspace_resources = await get_workspace_resource_ids(
            db, tenant_id=tenant_id, workspace_id=workspace_id
        )
        for model_id in workspace_resources["model"]:
            model = await db.get(Model, model_id)
            if model is not None and model.type == "llm":
                return model

    if agent.model_id is None:
        raise ValueError("model_not_found")
    model = await db.get(Model, agent.model_id)
    if model is None or model.type != "llm":
        raise ValueError("model_not_found")
    return model


def empty_context(
    agent: Agent, conversation: Conversation, query: str, intent: dict[str, Any]
) -> ContextBuildOut:
    user_message = ContextMessageOut(
        role="user", content=query, tokens=estimate_tokens(query)
    )
    return ContextBuildOut(
        agent_id=agent.id,
        conversation_id=conversation.id,
        workspace_id=conversation.workspace_id,
        messages=[user_message],
        tools=[],
        retrieved_chunks=[],
        citations=[],
        token_budget={
            "max": user_message.tokens,
            "system": 0,
            "knowledge": 0,
            "history": 0,
            "user": user_message.tokens,
            "total": user_message.tokens,
        },
        truncation={"policy_blocked": True},
        intent=intent,
        compression_strategy="recent_only",
        compression_applied=False,
        original_history_tokens=0,
        compressed_history_tokens=0,
        compressed_message_count=0,
        compression_fallback=False,
    )


async def persist_fallback_run(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    conversation: Conversation,
    agent: Agent,
    query: str,
    context: ContextBuildOut,
    fallback: FallbackResult,
    trace_name: str,
    user_id: UUID,
) -> AgentRunOut:
    started = time.perf_counter()
    user_message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        role="user",
        content=query,
        tokens=estimate_tokens(query),
        citations=[],
    )
    assistant_message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        role="assistant",
        content=fallback.message or "",
        tokens=estimate_tokens(fallback.message or ""),
        citations=[],
    )
    root_trace = RunTrace(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        agent_id=agent.id,
        span_type="agent",
        name=trace_name,
        status="ok",
        input={
            "query": query,
            "workspace_id": str(conversation.workspace_id)
            if conversation.workspace_id
            else None,
            "intent": context.intent,
            "context": {
                "token_budget": context.token_budget,
                "truncation": context.truncation,
                "tool_count": len(context.tools),
                "citation_count": len(context.citations),
                "compression": context_compression_summary(context),
            },
        },
        output={
            "answer": fallback.message,
            "usage": {},
            "tool_results": [],
            "citations": [],
            "intent": context.intent,
            "compression": context_compression_summary(context),
            "fallback": fallback.as_dict(),
        },
        tokens=assistant_message.tokens,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    db.add(user_message)
    db.add(assistant_message)
    db.add(root_trace)
    await db.flush()
    await db.commit()
    await db.refresh(user_message)
    await db.refresh(assistant_message)
    await db.refresh(root_trace)
    await archive_runtime_incidents(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation=conversation,
        agent=agent,
        user_message_id=user_message.id,
        assistant_message_id=assistant_message.id,
        trace_id=root_trace.id,
        query=query,
        answer=fallback.message or "",
        fallback=fallback,
        tool_results=[],
        citations=[],
    )
    return AgentRunOut(
        conversation_id=conversation.id,
        user_message_id=user_message.id,
        assistant_message_id=assistant_message.id,
        trace_id=root_trace.id,
        answer=fallback.message or "",
        citations=[],
        tool_results=[],
        usage={},
        context=context,
        intent=context.intent,
        fallback_applied=True,
        fallback_reason=fallback.reason,
        fallback_message=fallback.message,
    )


async def commit_fallback_root_trace(
    db: AsyncSession,
    *,
    root_trace: RunTrace,
    started: float,
    context: ContextBuildOut,
    intent: dict[str, Any],
    fallback: FallbackResult,
    usage: dict[str, Any],
    tool_results: list[RuntimeToolCallOut],
) -> None:
    root_trace.status = "failed" if fallback.reason == "model_error" else "ok"
    root_trace.output = {
        "answer": fallback.message,
        "usage": usage,
        "tool_results": [result.model_dump(mode="json") for result in tool_results],
        "citations": [citation.model_dump(mode="json") for citation in context.citations],
        "intent": intent,
        "compression": context_compression_summary(context),
        "fallback": fallback.as_dict(),
    }
    root_trace.tokens = int(
        (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
    )
    root_trace.latency_ms = int((time.perf_counter() - started) * 1000)
    await db.flush()


def stream_done_payload(result: AgentRunOut) -> dict[str, Any]:
    return {
        "conversation_id": str(result.conversation_id),
        "user_message_id": str(result.user_message_id),
        "assistant_message_id": str(result.assistant_message_id),
        "trace_id": str(result.trace_id),
        "usage": result.usage,
        "tool_results": [tool.model_dump(mode="json") for tool in result.tool_results],
        "citation_count": len(result.citations),
        "intent": result.intent,
        "compression_strategy": result.context.compression_strategy,
        "compression_applied": result.context.compression_applied,
        "original_history_tokens": result.context.original_history_tokens,
        "compressed_history_tokens": result.context.compressed_history_tokens,
        "compressed_message_count": result.context.compressed_message_count,
        "compression_fallback": result.context.compression_fallback,
        "status": "fallback" if result.fallback_applied else "ok",
        "fallback_applied": result.fallback_applied,
        "fallback_reason": result.fallback_reason,
        "fallback_message": result.fallback_message,
    }


async def archive_runtime_incidents(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    conversation: Conversation,
    agent: Agent,
    user_message_id: UUID,
    assistant_message_id: UUID,
    trace_id: UUID,
    query: str,
    answer: str,
    fallback: FallbackResult,
    tool_results: list[RuntimeToolCallOut],
    citations: list[Any],
) -> None:
    detail = {
        "query": query,
        "answer": answer,
        "fallback_reason": fallback.reason,
        "tool_results": [result.model_dump(mode="json") for result in tool_results],
        "citation_count": len(citations),
    }
    if fallback.applied:
        incident_type = (
            "no_citation" if fallback.reason == "retrieval_empty" else "fallback_applied"
        )
        await create_incident_safe(
            db,
            tenant_id=tenant_id,
            payload=incident_from_runtime(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                message_id=assistant_message_id,
                agent_id=agent.id,
                trace_id=trace_id,
                incident_type=incident_type,
                severity="medium" if incident_type == "no_citation" else "low",
                title=f"运行触发 fallback：{fallback.reason}",
                query=query,
                answer=answer,
                detail=detail,
            ),
            created_by=user_id,
        )
    if fallback.reason == "model_error":
        await create_incident_safe(
            db,
            tenant_id=tenant_id,
            payload=incident_from_runtime(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                message_id=assistant_message_id,
                agent_id=agent.id,
                trace_id=trace_id,
                incident_type="model_failed",
                severity="high",
                title="模型调用失败",
                query=query,
                answer=answer,
                detail=detail,
            ),
            created_by=user_id,
        )
    if any(result.status == "failed" for result in tool_results):
        await create_incident_safe(
            db,
            tenant_id=tenant_id,
            payload=incident_from_runtime(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                message_id=assistant_message_id,
                agent_id=agent.id,
                trace_id=trace_id,
                incident_type="tool_failed",
                severity="medium",
                title="工具调用失败",
                query=query,
                answer=answer,
                detail=detail,
            ),
            created_by=user_id,
        )


async def ensure_conversation(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    agent: Agent,
    conversation_id: UUID | None,
    workspace_id: UUID | None,
    title: str,
) -> Conversation:
    if conversation_id is not None:
        conversation = await db.get(Conversation, conversation_id)
        if (
            conversation is None
            or conversation.tenant_id != tenant_id
            or conversation.agent_id != agent.id
        ):
            raise ValueError("conversation_not_found")
        if workspace_id is not None and conversation.workspace_id != workspace_id:
            raise ValueError("workspace_mismatch")
        return conversation

    if workspace_id is not None:
        if (
            await load_workspace(db, tenant_id=tenant_id, workspace_id=workspace_id)
            is None
        ):
            raise ValueError("workspace_not_found")
        workspace_resources = await get_workspace_resource_ids(
            db, tenant_id=tenant_id, workspace_id=workspace_id
        )
        if (
            workspace_resources["agent"]
            and agent.id not in workspace_resources["agent"]
        ):
            raise ValueError("agent_not_in_workspace")

    conversation = Conversation(
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=agent.id,
        workspace_id=workspace_id,
        title=title[:80],
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def call_maas_chat(
    db: AsyncSession,
    tenant_id: UUID,
    conversation_id: UUID,
    agent_id: UUID,
    parent_trace_id: UUID,
    model_name: str,
    agent: Agent,
    messages: list[dict[str, str | None]],
    *,
    name: str = "maas_chat",
) -> dict[str, Any]:
    config = agent.config or {}
    request = {
        "model": model_name,
        "messages": messages,
        "stream": False,
        "temperature": config.get("temperature"),
        "max_tokens": config.get("max_output_tokens"),
    }
    request = {key: value for key, value in request.items() if value is not None}
    trace = RunTrace(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        agent_id=agent_id,
        parent_id=parent_trace_id,
        span_type="model",
        name=name,
        status="running",
        input={"model": model_name, "message_count": len(messages)},
        output={},
    )
    db.add(trace)
    await db.flush()
    started = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=upstream_timeout()) as client:
            response = await client.post(
                f"{settings.maas_base_url.rstrip('/')}/v1/chat/completions",
                json=request,
                headers=maas_service_headers(),
            )
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage") or {}
        trace.status = "ok"
        trace.output = {
            "finish_reason": ((data.get("choices") or [{}])[0]).get("finish_reason"),
            "usage": usage,
        }
        trace.tokens = int(
            (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
        )
        trace.latency_ms = int((time.perf_counter() - started) * 1000)
        await db.flush()
        return data
    except httpx.HTTPError as exc:
        error = runtime_error(exc)
        trace.status = "failed"
        trace.output = {"error": error.code, "detail": error.detail}
        trace.latency_ms = int((time.perf_counter() - started) * 1000)
        await db.flush()
        raise error from exc


async def call_maas_chat_stream(
    db: AsyncSession,
    tenant_id: UUID,
    conversation_id: UUID,
    agent_id: UUID,
    parent_trace_id: UUID,
    model_name: str,
    agent: Agent,
    messages: list[dict[str, str | None]],
    *,
    name: str = "maas_chat_stream",
) -> AsyncGenerator[dict[str, Any], None]:
    config = agent.config or {}
    request = {
        "model": model_name,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": config.get("temperature"),
        "max_tokens": config.get("max_output_tokens"),
    }
    request = {key: value for key, value in request.items() if value is not None}
    trace = RunTrace(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        agent_id=agent_id,
        parent_id=parent_trace_id,
        span_type="model",
        name=name,
        status="running",
        input={"model": model_name, "message_count": len(messages), "stream": True},
        output={},
    )
    db.add(trace)
    await db.flush()
    started = time.perf_counter()
    usage: dict[str, Any] = {}
    finish_reason = None

    try:
        async with httpx.AsyncClient(timeout=upstream_timeout()) as client:
            async with client.stream(
                "POST",
                f"{settings.maas_base_url.rstrip('/')}/v1/chat/completions",
                json=request,
                headers=maas_service_headers(),
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    raise OrchestratorError(maas_stream_error_detail(body))
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if payload.get("error"):
                        error = payload["error"]
                        raise OrchestratorError(
                            error.get("code") or "maas_stream_failed",
                            error.get("message"),
                        )
                    if payload.get("usage"):
                        usage = payload["usage"]
                        yield {"type": "usage", "usage": usage}
                    for choice in payload.get("choices") or []:
                        finish_reason = choice.get("finish_reason") or finish_reason
                        delta = choice.get("delta") or {}
                        text = delta.get("content")
                        if text:
                            yield {"type": "delta", "text": text}
        trace.status = "ok"
        trace.output = {"finish_reason": finish_reason, "usage": usage}
        trace.tokens = int(
            (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
        )
        trace.latency_ms = int((time.perf_counter() - started) * 1000)
        await db.flush()
    except ValueError as exc:
        error = runtime_error(exc)
        trace.status = "failed"
        trace.output = {"error": error.code}
        trace.latency_ms = int((time.perf_counter() - started) * 1000)
        await db.flush()
        raise error from exc
    except httpx.HTTPError as exc:
        error = runtime_error(exc)
        trace.status = "failed"
        trace.output = {"error": error.code, "detail": error.detail}
        trace.latency_ms = int((time.perf_counter() - started) * 1000)
        await db.flush()
        raise error from exc


def maas_stream_error_detail(body: bytes) -> str:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "maas_stream_failed"
    detail = payload.get("detail")
    if isinstance(detail, str) and detail:
        return detail
    return "maas_stream_failed"


def maas_error_detail(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "maas_timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            payload = exc.response.json()
        except ValueError:
            return "maas_call_failed"
        detail = payload.get("detail")
        if isinstance(detail, str) and detail:
            return detail
    return "maas_call_failed"


def runtime_error(exc: Exception) -> OrchestratorError:
    if isinstance(exc, OrchestratorError):
        return exc
    if isinstance(exc, httpx.HTTPError):
        return OrchestratorError(maas_error_detail(exc), str(exc))
    if is_dependency_exception(exc):
        return OrchestratorError("dependency_unavailable", str(exc))
    if isinstance(exc, ValueError):
        return OrchestratorError(str(exc))
    return OrchestratorError("agent_execution_failed", str(exc))


def is_dependency_exception(exc: Exception) -> bool:
    module = exc.__class__.__module__.split(".", maxsplit=1)[0]
    if module in {"redis", "minio"}:
        return True
    return isinstance(exc, (ConnectionError, TimeoutError))


async def commit_failed_root_trace(
    db: AsyncSession,
    *,
    root_trace: RunTrace,
    started: float,
    error: OrchestratorError,
    usage: dict[str, Any] | None = None,
    tool_results: list[RuntimeToolCallOut] | None = None,
    citations: list[Any] | None = None,
) -> None:
    root_trace.status = "failed"
    root_trace.output = {"error": error.code}
    if tool_results is not None:
        root_trace.output["tool_results"] = [
            result.model_dump(mode="json") for result in tool_results
        ]
    if citations is not None:
        root_trace.output["citations"] = [
            citation.model_dump(mode="json")
            if hasattr(citation, "model_dump")
            else citation
            for citation in citations
        ]
    if usage:
        root_trace.output["usage"] = usage
    root_trace.latency_ms = int((time.perf_counter() - started) * 1000)
    await db.flush()
    await db.commit()


def tool_exception_error(
    tool_results: list[RuntimeToolCallOut],
) -> OrchestratorError | None:
    failed = next(
        (
            result
            for result in tool_results
            if result.status == "failed"
            and result.output.get("error") == "tool_execution_failed"
        ),
        None,
    )
    if failed is None:
        return None
    return OrchestratorError(
        "tool_execution_failed", failed.output.get("detail") or "tool_execution_failed"
    )


def upstream_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        connect=settings.upstream_connect_timeout,
        read=settings.upstream_read_timeout,
        write=settings.upstream_write_timeout,
        pool=settings.upstream_pool_timeout,
    )


async def run_tool_loop(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    agent: Agent,
    parent_trace_id: UUID,
    context: ContextBuildOut,
    assistant_text: str,
    requested_tool_calls: list[RuntimeToolCallIn],
    max_tool_rounds: int,
) -> list[RuntimeToolCallOut]:
    if max_tool_rounds <= 0:
        return []

    tool_calls = list(requested_tool_calls)
    if not tool_calls:
        tool_calls = parse_tool_calls(assistant_text)
    if not tool_calls:
        return []

    repo = ToolRepository(db, tenant_id)
    available_by_id = {tool.id: tool for tool in context.tools}
    available_by_name = {tool.name: tool for tool in context.tools}
    results: list[RuntimeToolCallOut] = []
    for call in tool_calls[:max_tool_rounds]:
        context_tool = None
        if call.tool_id is not None:
            context_tool = available_by_id.get(call.tool_id)
        if context_tool is None and call.tool_name is not None:
            context_tool = available_by_name.get(call.tool_name)
        if context_tool is None:
            if call.tool_id is not None:
                results.append(
                    RuntimeToolCallOut(
                        tool_id=call.tool_id,
                        tool_name=call.tool_name or "unknown",
                        input=call.input,
                        output={"error": "tool_not_bound"},
                        status="failed",
                    )
                )
            continue

        tool = await repo.get_by_id(context_tool.id)
        if tool is None or tool.status != "active":
            results.append(
                RuntimeToolCallOut(
                    tool_id=context_tool.id,
                    tool_name=context_tool.name,
                    input=call.input,
                    output={"error": "tool_not_found"},
                    status="failed",
                )
            )
            continue

        results.append(
            await execute_bound_tool_call(
                db,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                agent=agent,
                parent_trace_id=parent_trace_id,
                tool=tool,
                call=call,
            )
        )
    return results


async def execute_bound_tool_call(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    agent: Agent,
    parent_trace_id: UUID,
    tool: Tool,
    call: RuntimeToolCallIn,
) -> RuntimeToolCallOut:
    trace = RunTrace(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        agent_id=agent.id,
        parent_id=parent_trace_id,
        span_type="tool",
        name=tool.name,
        status="running",
        input={"tool_id": str(tool.id), "input": call.input},
        output={},
    )
    db.add(trace)
    await db.flush()
    started = time.perf_counter()
    try:
        output = await run_tool(
            db, tenant_id=tenant_id, tool_id=tool.id, input=call.input
        )
    except Exception as exc:
        result = RuntimeToolCallOut(
            tool_id=tool.id,
            tool_name=tool.name,
            input=call.input,
            output={"error": "tool_execution_failed", "detail": str(exc)},
            status="failed",
        )
    else:
        if output is None:
            result = RuntimeToolCallOut(
                tool_id=tool.id,
                tool_name=tool.name,
                input=call.input,
                output={"error": "tool_not_found"},
                status="failed",
            )
        else:
            result = RuntimeToolCallOut(
                tool_id=tool.id,
                tool_name=tool.name,
                input=call.input,
                output=output.output,
                status=output.status,
            )
            trace.output = output.model_dump(mode="json")

    trace.status = result.status
    if not trace.output:
        trace.output = result.model_dump(mode="json")
    trace.latency_ms = int((time.perf_counter() - started) * 1000)
    await db.flush()
    return result


def parse_tool_calls(text: str) -> list[RuntimeToolCallIn]:
    payload = extract_json_payload(text)
    if payload is None:
        return []

    calls = payload.get("tool_calls") if isinstance(payload, dict) else payload
    if not isinstance(calls, list):
        return []

    parsed: list[RuntimeToolCallIn] = []
    for item in calls:
        if not isinstance(item, dict):
            continue
        parsed.append(
            RuntimeToolCallIn(
                tool_id=item.get("tool_id"),
                tool_name=item.get("tool_name") or item.get("name"),
                input=item.get("input") or {},
            )
        )
    return parsed


def auto_tool_calls(
    agent: Agent, context: ContextBuildOut, query: str
) -> list[RuntimeToolCallIn]:
    if agent.type != "nl2data" or not context.tools:
        return []
    tool = next(
        (
            item
            for item in context.tools
            if item.name in {"text2sql", "nl2data", "12345问数"}
        ),
        context.tools[0],
    )
    return [RuntimeToolCallIn(tool_id=tool.id, input={"question": query})]


def extract_json_payload(text: str) -> Any | None:
    start_candidates = [
        index for index in (text.find("{"), text.find("[")) if index >= 0
    ]
    if not start_candidates:
        return None
    start = min(start_candidates)
    for end in range(len(text), start, -1):
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            continue
    return None


def tool_result_prompt(results: list[RuntimeToolCallOut]) -> str:
    serialized = [result.model_dump(mode="json") for result in results]
    return "工具执行结果如下，请基于结果给出最终回答：\n" + json.dumps(
        serialized, ensure_ascii=False
    )


def format_nl2data_answer(results: list[RuntimeToolCallOut]) -> str:
    if not results:
        return "没有可用的数据查询结果。"
    output = results[-1].output
    if output.get("error"):
        return f"问数失败：{output.get('detail') or output['error']}"
    lines = [
        output.get("summary") or "查询完成。",
        "",
        f"SQL: {output.get('sql', '')}",
    ]
    rows = output.get("rows") or []
    if rows:
        lines.append("结果预览:")
        for row in rows[:10]:
            lines.append(
                "- " + "，".join(f"{key}={value}" for key, value in row.items())
            )
    return "\n".join(lines)


def format_tool_failure_answer(results: list[RuntimeToolCallOut]) -> str:
    failed = next((result for result in results if result.status == "failed"), None)
    if failed is None:
        return "工具执行失败。"
    error = failed.output.get("error") or "tool_execution_failed"
    detail = failed.output.get("detail")
    if detail:
        return f"工具 {failed.tool_name} 执行失败：{detail}"
    return f"工具 {failed.tool_name} 执行失败：{error}"


def context_rerank_summary(context: ContextBuildOut) -> dict[str, Any]:
    modes = [citation.rerank_mode for citation in context.citations if citation.rerank_mode]
    scores = [
        citation.rerank_score
        for citation in context.citations
        if citation.rerank_score is not None
    ]
    return {
        "mode": modes[0] if modes else "off",
        "fallback": any(bool(citation.rerank_fallback) for citation in context.citations),
        "citation_count": len(context.citations),
        "reranked_count": len(scores),
    }


def context_compression_summary(context: ContextBuildOut) -> dict[str, Any]:
    return {
        "strategy": context.compression_strategy,
        "applied": context.compression_applied,
        "original_history_tokens": context.original_history_tokens,
        "compressed_history_tokens": context.compressed_history_tokens,
        "compressed_message_count": context.compressed_message_count,
        "fallback": context.compression_fallback,
        "summary_preview": context.compression_summary[:500]
        if context.compression_summary
        else None,
    }


def extract_answer(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return message.get("content") or ""
