import json
import time
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Agent, Conversation, Message, Model, RunTrace, Tool
from app.orchestrator.context import build_agent_context, estimate_tokens
from app.repositories import AgentRepository
from app.schemas import AgentRunIn, AgentRunOut, ContextBuildOut, RuntimeToolCallIn, RuntimeToolCallOut
from app.services import run_tool
from app.services.workspace_service import get_workspace_resource_ids, load_workspace


async def dispatch_single_agent(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    agent_id: UUID,
    payload: AgentRunIn,
) -> AgentRunOut | None:
    return await run_agent(db, tenant_id=tenant_id, user_id=user_id, agent_id=agent_id, payload=payload)


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
    if agent is None or agent.status != "active":
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
    model = await load_llm_model(db, tenant_id=tenant_id, agent=agent, workspace_id=conversation.workspace_id)
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
    )
    if context is None:
        return None

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
            "workspace_id": str(conversation.workspace_id) if conversation.workspace_id else None,
            "model": model.name,
            "context": {
                "token_budget": context.token_budget,
                "truncation": context.truncation,
                "tool_count": len(context.tools),
                "citation_count": len(context.citations),
            },
        },
        output={},
        tokens=0,
        latency_ms=0,
    )
    db.add(root_trace)
    await db.flush()

    started = time.perf_counter()
    messages = [{"role": message.role, "content": message.content} for message in context.messages]
    first_response = await call_maas_chat(db, tenant_id, conversation.id, agent.id, root_trace.id, model.name, agent, messages)
    first_answer = extract_answer(first_response)
    requested_tool_calls = payload.tool_calls or auto_tool_calls(agent, context, payload.query)

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
    if tool_results:
        messages.append({"role": "assistant", "content": first_answer})
        messages.append({"role": "user", "content": tool_result_prompt(tool_results)})
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

    usage = final_response.get("usage") or {}
    assistant_message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        role="assistant",
        content=answer,
        tokens=estimate_tokens(answer),
        citations=[citation.model_dump(mode="json") for citation in context.citations],
    )
    db.add(assistant_message)
    root_trace.status = "ok"
    root_trace.output = {
        "answer": answer,
        "usage": usage,
        "tool_results": [result.model_dump(mode="json") for result in tool_results],
        "citations": [citation.model_dump(mode="json") for citation in context.citations],
    }
    root_trace.tokens = int((usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0))
    root_trace.latency_ms = int((time.perf_counter() - started) * 1000)
    await db.flush()
    await db.commit()
    await db.refresh(user_message)
    await db.refresh(assistant_message)
    await db.refresh(root_trace)

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
    )


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
    if agent is None or agent.status != "active":
        yield {"event": "error", "data": {"detail": "agent_not_found"}}
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
    model = await load_llm_model(db, tenant_id=tenant_id, agent=agent, workspace_id=conversation.workspace_id)
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
    )
    if context is None:
        yield {"event": "error", "data": {"detail": "agent_not_found"}}
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
            "workspace_id": str(conversation.workspace_id) if conversation.workspace_id else None,
            "model": model.name,
            "context": {
                "token_budget": context.token_budget,
                "truncation": context.truncation,
                "tool_count": len(context.tools),
                "citation_count": len(context.citations),
            },
        },
        output={},
        tokens=0,
        latency_ms=0,
    )
    db.add(root_trace)
    await db.flush()

    for citation in context.citations:
        yield {"event": "citation", "data": citation.model_dump(mode="json")}

    started = time.perf_counter()
    messages = [{"role": message.role, "content": message.content} for message in context.messages]
    answer_parts: list[str] = []
    usage: dict[str, Any] = {}
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
                text = event["text"]
                answer_parts.append(text)
                yield {"event": "delta", "data": {"text": text}}
            elif event["type"] == "usage":
                usage = event["usage"]
    except ValueError as exc:
        root_trace.status = "failed"
        root_trace.output = {"error": str(exc)}
        root_trace.latency_ms = int((time.perf_counter() - started) * 1000)
        await db.flush()
        await db.commit()
        yield {"event": "error", "data": {"detail": str(exc)}}
        return

    answer = "".join(answer_parts)
    tool_results = await run_tool_loop(
        db,
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        agent=agent,
        parent_trace_id=root_trace.id,
        context=context,
        assistant_text=answer,
        requested_tool_calls=payload.tool_calls or auto_tool_calls(agent, context, payload.query),
        max_tool_rounds=payload.max_tool_rounds,
    )
    if tool_results:
        final_messages = [*messages, {"role": "assistant", "content": answer}, {"role": "user", "content": tool_result_prompt(tool_results)}]
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

    assistant_message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        role="assistant",
        content=answer,
        tokens=estimate_tokens(answer),
        citations=[citation.model_dump(mode="json") for citation in context.citations],
    )
    db.add(assistant_message)
    root_trace.status = "ok"
    root_trace.output = {
        "answer": answer,
        "usage": usage,
        "tool_results": [result.model_dump(mode="json") for result in tool_results],
        "citations": [citation.model_dump(mode="json") for citation in context.citations],
    }
    root_trace.tokens = int((usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0))
    root_trace.latency_ms = int((time.perf_counter() - started) * 1000)
    await db.flush()
    await db.commit()
    await db.refresh(user_message)
    await db.refresh(assistant_message)
    await db.refresh(root_trace)
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
        },
    }


async def load_llm_model(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    agent: Agent,
    workspace_id: UUID | None,
) -> Model:
    if workspace_id is not None:
        workspace_resources = await get_workspace_resource_ids(db, tenant_id=tenant_id, workspace_id=workspace_id)
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
        if conversation is None or conversation.tenant_id != tenant_id or conversation.agent_id != agent.id:
            raise ValueError("conversation_not_found")
        if workspace_id is not None and conversation.workspace_id != workspace_id:
            raise ValueError("workspace_mismatch")
        return conversation

    if workspace_id is not None:
        if await load_workspace(db, tenant_id=tenant_id, workspace_id=workspace_id) is None:
            raise ValueError("workspace_not_found")
        workspace_resources = await get_workspace_resource_ids(db, tenant_id=tenant_id, workspace_id=workspace_id)
        if workspace_resources["agent"] and agent.id not in workspace_resources["agent"]:
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
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(f"{settings.maas_base_url.rstrip('/')}/v1/chat/completions", json=request)
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage") or {}
        trace.status = "ok"
        trace.output = {
            "finish_reason": ((data.get("choices") or [{}])[0]).get("finish_reason"),
            "usage": usage,
        }
        trace.tokens = int((usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0))
        trace.latency_ms = int((time.perf_counter() - started) * 1000)
        await db.flush()
        return data
    except httpx.HTTPError as exc:
        detail = maas_error_detail(exc)
        trace.status = "failed"
        trace.output = {"error": detail, "detail": str(exc)}
        trace.latency_ms = int((time.perf_counter() - started) * 1000)
        await db.flush()
        raise ValueError(detail) from exc


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
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{settings.maas_base_url.rstrip('/')}/v1/chat/completions",
                json=request,
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    raise ValueError(maas_stream_error_detail(body))
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
                        raise ValueError(error.get("message") or "maas_stream_failed")
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
        trace.tokens = int((usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0))
        trace.latency_ms = int((time.perf_counter() - started) * 1000)
        await db.flush()
    except ValueError as exc:
        trace.status = "failed"
        trace.output = {"error": str(exc)}
        trace.latency_ms = int((time.perf_counter() - started) * 1000)
        await db.flush()
        raise
    except httpx.HTTPError as exc:
        detail = maas_error_detail(exc)
        trace.status = "failed"
        trace.output = {"error": detail, "detail": str(exc)}
        trace.latency_ms = int((time.perf_counter() - started) * 1000)
        await db.flush()
        raise ValueError(detail) from exc


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
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            payload = exc.response.json()
        except ValueError:
            return "maas_call_failed"
        detail = payload.get("detail")
        if isinstance(detail, str) and detail:
            return detail
    return "maas_call_failed"


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

    available_by_id = {tool.id: tool for tool in context.tools}
    available_by_name = {tool.name: tool for tool in context.tools}
    results: list[RuntimeToolCallOut] = []
    for call in tool_calls[:max_tool_rounds]:
        tool = None
        if call.tool_id is not None:
            tool = available_by_id.get(call.tool_id)
        if tool is None and call.tool_name is not None:
            tool = available_by_name.get(call.tool_name)
        if tool is None:
            raise ValueError("tool_not_bound")

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
        output = await run_tool(db, tenant_id=tenant_id, tool_id=tool.id, input=call.input)
        if output is None:
            trace.status = "failed"
            trace.output = {"error": "tool_not_found"}
            await db.flush()
            raise ValueError("tool_not_found")

        trace.status = output.status
        trace.output = output.model_dump(mode="json")
        trace.latency_ms = int((time.perf_counter() - started) * 1000)
        await db.flush()
        results.append(
            RuntimeToolCallOut(
                tool_id=tool.id,
                tool_name=tool.name,
                input=call.input,
                output=output.output,
                status=output.status,
            )
        )
    return results


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


def auto_tool_calls(agent: Agent, context: ContextBuildOut, query: str) -> list[RuntimeToolCallIn]:
    if agent.type != "nl2data" or not context.tools:
        return []
    tool = next((item for item in context.tools if item.name in {"text2sql", "nl2data", "12345问数"}), context.tools[0])
    return [RuntimeToolCallIn(tool_id=tool.id, input={"question": query})]


def extract_json_payload(text: str) -> Any | None:
    start_candidates = [index for index in (text.find("{"), text.find("[")) if index >= 0]
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
    return "工具执行结果如下，请基于结果给出最终回答：\n" + json.dumps(serialized, ensure_ascii=False)


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
            lines.append("- " + "，".join(f"{key}={value}" for key, value in row.items()))
    return "\n".join(lines)


def extract_answer(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return message.get("content") or ""
