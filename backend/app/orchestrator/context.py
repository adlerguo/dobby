import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, Conversation, Message, Tool
from app.orchestrator.answer_style import ANSWER_STYLE_PROMPT
from app.rag.retrieve import retrieve_chunks
from app.repositories import AgentRepository
from app.schemas import CitationOut, ContextBuildOut, ContextMessageOut, ContextToolOut, RetrievedChunkOut
from app.services.workspace_service import get_workspace_resource_ids


@dataclass
class ContextParts:
    messages: list[ContextMessageOut]
    chunks: list[RetrievedChunkOut]
    citations: list[CitationOut]
    token_budget: dict[str, int]
    truncation: dict


async def build_agent_context(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    query: str,
    conversation_id: UUID | None = None,
    workspace_id: UUID | None = None,
    max_tokens: int = 3500,
    history_limit: int = 12,
    top_k: int | None = None,
    score_threshold: float | None = None,
    match_type: str | None = None,
) -> ContextBuildOut | None:
    repo = AgentRepository(db, tenant_id)
    agent = await repo.get_by_id(agent_id)
    if agent is None or agent.status == "archived":
        return None

    workspace_resources = await get_workspace_resource_ids(db, tenant_id=tenant_id, workspace_id=workspace_id)
    kb_ids = unique_ids([*(await repo.get_kb_ids(agent.id)), *workspace_resources["kb"]])
    tool_ids = unique_ids([*(await repo.get_tool_ids(agent.id)), *workspace_resources["tool"]])
    rag_config = resolve_rag_config(
        agent,
        request_top_k=top_k,
        request_score_threshold=score_threshold,
        request_match_type=match_type,
    )
    tools = await load_tools(db, tenant_id=tenant_id, tool_ids=tool_ids)
    history = await load_history(
        db,
        tenant_id=tenant_id,
        agent_id=agent.id,
        conversation_id=conversation_id,
        limit=history_limit,
    )
    retrieved_chunks, citations = await retrieve_agent_knowledge(
        db,
        tenant_id=tenant_id,
        kb_ids=kb_ids,
        query=query,
        top_k=rag_config["top_k"],
        score_threshold=rag_config["score_threshold"],
        match_type=str(rag_config["match_type"]),
    )

    parts = assemble_context_parts(
        agent=agent,
        query=query,
        conversation_id=conversation_id,
        tools=tools,
        history=history,
        chunks=retrieved_chunks,
        citations=citations,
        max_tokens=max_tokens,
        rag_config=rag_config,
    )
    return ContextBuildOut(
        agent_id=agent.id,
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        messages=parts.messages,
        tools=[tool_out(tool) for tool in tools],
        retrieved_chunks=parts.chunks,
        citations=parts.citations,
        token_budget=parts.token_budget,
        truncation=parts.truncation,
    )


async def load_tools(db: AsyncSession, *, tenant_id: UUID, tool_ids: list[UUID]) -> list[Tool]:
    if not tool_ids:
        return []
    result = await db.execute(
        select(Tool).where(Tool.tenant_id == tenant_id, Tool.id.in_(tool_ids), Tool.status == "active")
    )
    tools_by_id = {tool.id: tool for tool in result.scalars().all()}
    return [tools_by_id[tool_id] for tool_id in tool_ids if tool_id in tools_by_id]


async def load_history(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    conversation_id: UUID | None,
    limit: int,
) -> list[Message]:
    if conversation_id is None or limit <= 0:
        return []

    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
            Conversation.agent_id == agent_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise ValueError("conversation_not_found")

    result = await db.execute(
        select(Message)
        .where(Message.tenant_id == tenant_id, Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    return list(reversed(result.scalars().all()))


async def retrieve_agent_knowledge(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    kb_ids: list[UUID],
    query: str,
    top_k: int,
    score_threshold: float = 0.0,
    match_type: str = "hybrid",
) -> tuple[list[RetrievedChunkOut], list[CitationOut]]:
    chunks: list[RetrievedChunkOut] = []
    citations: list[CitationOut] = []
    for kb_id in kb_ids:
        result = await retrieve_chunks(
            db,
            tenant_id=tenant_id,
            kb_id=kb_id,
            query=query,
            top_k=top_k,
            match_type=match_type if match_type in {"hybrid", "vector", "keyword"} else "hybrid",
            score_threshold=score_threshold,
        )
        if result is None:
            continue
        chunks.extend(result.chunks)
        citations.extend(result.citations)

    ranked = sorted(zip(chunks, citations, strict=False), key=lambda pair: pair[0].score, reverse=True)
    ranked = ranked[:top_k]
    return [pair[0] for pair in ranked], [pair[1] for pair in ranked]


def resolve_rag_config(
    agent: Agent,
    *,
    request_top_k: int | None,
    request_score_threshold: float | None,
    request_match_type: str | None,
) -> dict[str, int | float | str]:
    config = agent.config or {}
    rag = config.get("rag") if isinstance(config.get("rag"), dict) else {}
    top_k = coerce_int(
        request_top_k if request_top_k is not None else rag.get("top_k"),
        default=4,
        minimum=1,
        maximum=20,
    )
    score_threshold = coerce_float(
        request_score_threshold if request_score_threshold is not None else rag.get("score_threshold"),
        default=0.0,
        minimum=0.0,
        maximum=1.0,
    )
    match_type = request_match_type if request_match_type is not None else rag.get("match_type")
    if match_type not in {"hybrid", "vector", "keyword"}:
        match_type = "hybrid"
    return {"top_k": top_k, "score_threshold": score_threshold, "match_type": match_type}


def coerce_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, minimum), maximum)


def coerce_float(value: object, *, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, minimum), maximum)


def assemble_context_parts(
    *,
    agent: Agent,
    query: str,
    conversation_id: UUID | None,
    tools: list[Tool],
    history: list[Message],
    chunks: list[RetrievedChunkOut],
    citations: list[CitationOut],
    max_tokens: int,
    rag_config: dict[str, int | float | str],
) -> ContextParts:
    user_message = ContextMessageOut(role="user", content=query, tokens=estimate_tokens(query))
    system_message = make_system_message(agent, tools)
    fixed_tokens = system_message.tokens + user_message.tokens
    remaining = max(max_tokens - fixed_tokens, 0)
    history_budget = remaining // 3
    knowledge_budget = remaining - history_budget

    history_messages, history_dropped = fit_history(history, history_budget)
    knowledge_message, included_chunks, included_citations, knowledge_truncation = fit_knowledge(
        chunks,
        citations,
        knowledge_budget,
    )

    messages = [system_message]
    if knowledge_message is not None:
        messages.append(knowledge_message)
    messages.extend(history_messages)
    messages.append(user_message)
    total_tokens = sum(message.tokens for message in messages)

    return ContextParts(
        messages=messages,
        chunks=included_chunks,
        citations=included_citations,
        token_budget={
            "max": max_tokens,
            "system": system_message.tokens,
            "knowledge": knowledge_message.tokens if knowledge_message is not None else 0,
            "history": sum(message.tokens for message in history_messages),
            "user": user_message.tokens,
            "total": total_tokens,
        },
        truncation={
            "conversation_id": str(conversation_id) if conversation_id is not None else None,
            "history_requested": len(history),
            "history_dropped": history_dropped,
            "retrieved_chunks": len(chunks),
            "included_chunks": len(included_chunks),
            "dropped_chunks": max(len(chunks) - len(included_chunks), 0),
            "knowledge_truncated": knowledge_truncation,
            "over_budget": total_tokens > max_tokens,
            "rag": rag_config,
        },
    )


def make_system_message(agent: Agent, tools: list[Tool]) -> ContextMessageOut:
    config = agent.config or {}
    persona = agent.persona or config.get("persona") or "你是企业智能体中台中的业务助手。"
    answer_style_enabled = config.get("answer_style_enabled", True) is not False
    lines = [
        persona,
        "",
        "运行规则：",
        "- 优先使用提供的知识片段回答；知识不足时明确说明不足。",
        "- 引用知识片段时保留片段编号，最终回答需要能追溯出处。",
        "- 需要调用工具时，只能选择可用工具清单中的工具。",
    ]
    if answer_style_enabled:
        lines.extend(["", ANSWER_STYLE_PROMPT])
    if tools:
        lines.extend(["", "可用工具清单："])
        for tool in tools:
            schema_text = json.dumps(tool.schema or {}, ensure_ascii=False, separators=(",", ":"))
            lines.append(f"- id={tool.id} name={tool.name} type={tool.type} schema={schema_text}")

    content = "\n".join(lines)
    return ContextMessageOut(role="system", content=content, tokens=estimate_tokens(content))


def fit_history(history: list[Message], budget: int) -> tuple[list[ContextMessageOut], int]:
    selected: list[ContextMessageOut] = []
    used = 0
    dropped = 0
    for message in reversed(history):
        content = message.content or ""
        tokens = estimate_tokens(content)
        if tokens + used <= budget:
            selected.append(ContextMessageOut(role=message.role, content=content, tokens=tokens))
            used += tokens
        else:
            dropped += 1
    selected.reverse()
    return selected, dropped


def fit_knowledge(
    chunks: list[RetrievedChunkOut],
    citations: list[CitationOut],
    budget: int,
) -> tuple[ContextMessageOut | None, list[RetrievedChunkOut], list[CitationOut], bool]:
    if not chunks or budget <= 0:
        return None, [], [], bool(chunks)

    lines = ["知识片段："]
    selected_chunks: list[RetrievedChunkOut] = []
    selected_citations: list[CitationOut] = []
    used = estimate_tokens("\n".join(lines))
    truncated = False

    for index, (chunk, citation) in enumerate(zip(chunks, citations, strict=False), start=1):
        prefix = f"[{index}] doc={citation.doc_name} chunk_id={chunk.id} score={chunk.score}\n"
        available = budget - used - estimate_tokens(prefix)
        if available <= 0:
            truncated = True
            break
        content = chunk.content
        content_tokens = estimate_tokens(content)
        if content_tokens > available:
            content = truncate_to_tokens(content, available)
            truncated = True
        block = prefix + content
        lines.append(block)
        used += estimate_tokens(block)
        selected_chunks.append(chunk.model_copy(update={"content": content}))
        selected_citations.append(citation)
        if truncated:
            break

    if not selected_chunks:
        return None, [], [], True
    content = "\n\n".join(lines)
    return ContextMessageOut(role="system", content=content, tokens=estimate_tokens(content)), selected_chunks, selected_citations, truncated


def tool_out(tool: Tool) -> ContextToolOut:
    return ContextToolOut(id=tool.id, name=tool.name, type=tool.type, tool_schema=tool.schema or {})


def unique_ids(ids: list[UUID]) -> list[UUID]:
    seen: set[UUID] = set()
    unique: list[UUID] = []
    for item in ids:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    other = len(text) - cjk
    return max(1, int(cjk * 1.2 + other / 4))


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    if estimate_tokens(text) <= max_tokens:
        return text

    low = 0
    high = len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if estimate_tokens(text[:mid]) <= max_tokens:
            low = mid
        else:
            high = mid - 1
    return text[:low].rstrip()
