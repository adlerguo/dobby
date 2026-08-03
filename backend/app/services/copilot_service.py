from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.errors import NotFoundError, ValidationError
from app.models import Agent, Document, KnowledgeBase
from app.orchestrator import dispatch_single_agent
from app.schemas import AgentCreate, AgentRunIn, AgentUpdate, KnowledgeBaseCreate
from app.schemas.copilot import CopilotExecuteIn, CopilotExecuteOut, CopilotToolOut
from app.services.agent_service import create_agent, get_agent, publish_agent, update_agent
from app.services.audit_service import write_audit
from app.services.kb_service import create_kb
from app.services.publish_service import run_publish_precheck, validate_publish_confirmation

ToolHandler = Callable[
    [AsyncSession, AuthContext, CopilotExecuteIn],
    Awaitable[tuple[str, UUID | None, dict[str, Any], dict[str, Any], dict[str, Any]]],
]


@dataclass(frozen=True)
class CopilotToolSpec:
    name: str
    description: str
    category: str
    risk_level: str
    requires_confirmation: bool
    permission: tuple[str, ...]
    input_schema: dict[str, Any]
    handler: ToolHandler


COPILOT_TOOL_REGISTRY: dict[str, CopilotToolSpec] = {}


def register_tool(spec: CopilotToolSpec) -> None:
    COPILOT_TOOL_REGISTRY[spec.name] = spec


def list_copilot_tools() -> list[CopilotToolOut]:
    return [
        CopilotToolOut(
            name=tool.name,
            description=tool.description,
            category=tool.category,
            risk_level=tool.risk_level,  # type: ignore[arg-type]
            requires_confirmation=tool.requires_confirmation,
            permission=list(tool.permission),
            input_schema=tool.input_schema,
        )
        for tool in COPILOT_TOOL_REGISTRY.values()
    ]


async def execute_copilot_tool(
    db: AsyncSession,
    *,
    auth: AuthContext,
    payload: CopilotExecuteIn,
    request: Request | None = None,
) -> CopilotExecuteOut:
    tool = COPILOT_TOOL_REGISTRY.get(payload.tool)
    if tool is None:
        raise NotFoundError(code="copilot_tool_not_found", message="工具不存在")
    ensure_tool_permission(auth, tool)
    if tool.requires_confirmation and not payload.confirmed:
        raise ValidationError(code="copilot_confirmation_required", message="请先确认变更预览")

    target_type, target_id, before, after, result = await tool.handler(db, auth, payload)
    audit_detail = {
        "tool": tool.name,
        "action": tool.name,
        "target_type": target_type,
        "target_id": str(target_id) if target_id else None,
        "before": sanitize_audit_payload(before),
        "after": sanitize_audit_payload(after),
        "confirmed_by": str(auth.user_id),
        "status": "success",
        "conversation_id": payload.conversation_id,
        "workspace_id": payload.workspace_id,
        "risk_level": tool.risk_level,
    }
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="copilot.tool_execute",
        resource_type=target_type,
        resource_id=target_id,
        detail=audit_detail,
        request=request,
    )
    return CopilotExecuteOut(
        tool=tool.name,
        status="success",
        message="操作已完成",
        target_type=target_type,
        target_id=target_id,
        result=result,
        audit={
            "action": "copilot.tool_execute",
            "risk_level": tool.risk_level,
            "confirmed_by": str(auth.user_id),
        },
    )


def ensure_tool_permission(auth: AuthContext, tool: CopilotToolSpec) -> None:
    if "super_admin" in auth.roles:
        return
    missing = [permission for permission in tool.permission if permission not in auth.permissions]
    if missing:
        raise ValidationError(
            code="copilot_permission_denied",
            message="当前账号没有执行该操作的权限",
            detail={"missing": missing},
        )


def value(data: dict[str, Any], key: str, default: Any = None) -> Any:
    return data.get(key, default)


def uuid_list(raw: Any) -> list[UUID]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValidationError(code="invalid_uuid_list", message="参数格式错误")
    return [UUID(str(item)) for item in raw if str(item).strip()]


async def handle_create_agent(
    db: AsyncSession, auth: AuthContext, payload: CopilotExecuteIn
) -> tuple[str, UUID | None, dict[str, Any], dict[str, Any], dict[str, Any]]:
    data = payload.input
    create_payload = AgentCreate(
        name=str(value(data, "name", "")).strip(),
        type=str(value(data, "type", "qa")),
        persona=value(data, "persona"),
        model_id=UUID(str(data["model_id"])) if value(data, "model_id") else None,
        kb_ids=uuid_list(value(data, "kb_ids", [])),
        tool_ids=uuid_list(value(data, "tool_ids", [])),
        config=dict(value(data, "config", {}) or {}),
    )
    agent = await create_agent(db, tenant_id=auth.tenant_id, user_id=auth.user_id, payload=create_payload)
    after = agent.model_dump(mode="json")
    return "agent", agent.id, {}, after, {"agent": after}


async def handle_create_kb(
    db: AsyncSession, auth: AuthContext, payload: CopilotExecuteIn
) -> tuple[str, UUID | None, dict[str, Any], dict[str, Any], dict[str, Any]]:
    data = payload.input
    create_payload = KnowledgeBaseCreate(
        name=str(value(data, "name", "")).strip(),
        type=str(value(data, "type", "doc_regulation")),
        description=value(data, "description"),
        config=dict(value(data, "config", {}) or {}),
        embedding_model=str(value(data, "embedding_model", "mock-embedding")),
    )
    kb = await create_kb(db, tenant_id=auth.tenant_id, created_by=auth.user_id, payload=create_payload)
    after = kb.model_dump(mode="json")
    return "kb", kb.id, {}, after, {"knowledge_base": after}


async def handle_change_model(
    db: AsyncSession, auth: AuthContext, payload: CopilotExecuteIn
) -> tuple[str, UUID | None, dict[str, Any], dict[str, Any], dict[str, Any]]:
    agent_id = UUID(str(payload.input["agent_id"]))
    before_agent = await get_agent(db, tenant_id=auth.tenant_id, agent_id=agent_id)
    if before_agent is None:
        raise NotFoundError(code="agent_not_found", message="智能体不存在")
    model_id = UUID(str(payload.input["model_id"]))
    updated = await update_agent(db, tenant_id=auth.tenant_id, agent_id=agent_id, payload=AgentUpdate(model_id=model_id))
    assert updated is not None
    before = {"model_id": str(before_agent.model_id) if before_agent.model_id else None}
    after = {"model_id": str(updated.model_id) if updated.model_id else None}
    return "agent", updated.id, before, after, {"agent": updated.model_dump(mode="json")}


async def handle_bind_knowledge(
    db: AsyncSession, auth: AuthContext, payload: CopilotExecuteIn
) -> tuple[str, UUID | None, dict[str, Any], dict[str, Any], dict[str, Any]]:
    agent_id = UUID(str(payload.input["agent_id"]))
    before_agent = await get_agent(db, tenant_id=auth.tenant_id, agent_id=agent_id)
    if before_agent is None:
        raise NotFoundError(code="agent_not_found", message="智能体不存在")
    new_ids = uuid_list(payload.input.get("kb_ids"))
    merged = list(dict.fromkeys([*before_agent.kb_ids, *new_ids]))
    updated = await update_agent(db, tenant_id=auth.tenant_id, agent_id=agent_id, payload=AgentUpdate(kb_ids=merged))
    assert updated is not None
    before = {"kb_ids": [str(item) for item in before_agent.kb_ids]}
    after = {"kb_ids": [str(item) for item in updated.kb_ids]}
    return "agent", updated.id, before, after, {"agent": updated.model_dump(mode="json")}


async def handle_bind_tool(
    db: AsyncSession, auth: AuthContext, payload: CopilotExecuteIn
) -> tuple[str, UUID | None, dict[str, Any], dict[str, Any], dict[str, Any]]:
    agent_id = UUID(str(payload.input["agent_id"]))
    before_agent = await get_agent(db, tenant_id=auth.tenant_id, agent_id=agent_id)
    if before_agent is None:
        raise NotFoundError(code="agent_not_found", message="智能体不存在")
    new_ids = uuid_list(payload.input.get("tool_ids"))
    merged = list(dict.fromkeys([*before_agent.tool_ids, *new_ids]))
    updated = await update_agent(db, tenant_id=auth.tenant_id, agent_id=agent_id, payload=AgentUpdate(tool_ids=merged))
    assert updated is not None
    before = {"tool_ids": [str(item) for item in before_agent.tool_ids]}
    after = {"tool_ids": [str(item) for item in updated.tool_ids]}
    return "agent", updated.id, before, after, {"agent": updated.model_dump(mode="json")}


async def handle_update_prompt(
    db: AsyncSession, auth: AuthContext, payload: CopilotExecuteIn
) -> tuple[str, UUID | None, dict[str, Any], dict[str, Any], dict[str, Any]]:
    agent_id = UUID(str(payload.input["agent_id"]))
    before_agent = await get_agent(db, tenant_id=auth.tenant_id, agent_id=agent_id)
    if before_agent is None:
        raise NotFoundError(code="agent_not_found", message="智能体不存在")
    persona = str(payload.input.get("persona") or "").strip()
    updated = await update_agent(db, tenant_id=auth.tenant_id, agent_id=agent_id, payload=AgentUpdate(persona=persona))
    assert updated is not None
    before = {"persona": before_agent.persona}
    after = {"persona": updated.persona}
    return "agent", updated.id, before, after, {"agent": updated.model_dump(mode="json")}


async def handle_kb_status(
    db: AsyncSession, auth: AuthContext, payload: CopilotExecuteIn
) -> tuple[str, UUID | None, dict[str, Any], dict[str, Any], dict[str, Any]]:
    kb_id = UUID(str(payload.input["kb_id"]))
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None or kb.tenant_id != auth.tenant_id:
        raise NotFoundError(code="kb_not_found", message="知识库不存在")
    counts = await kb_document_counts(db, tenant_id=auth.tenant_id, kb_id=kb.id)
    ready = counts["processing"] == 0 and counts["failed"] == 0 and counts["done"] > 0
    result = {
        "id": str(kb.id),
        "name": kb.name,
        "status": kb.status,
        "ready": ready,
        "document_counts": counts,
    }
    return "kb", kb.id, {}, result, {"knowledge_base_status": result}


async def handle_kb_check_readiness(
    db: AsyncSession, auth: AuthContext, payload: CopilotExecuteIn
) -> tuple[str, UUID | None, dict[str, Any], dict[str, Any], dict[str, Any]]:
    return await handle_kb_status(db, auth, payload)


async def handle_generate_test_cases(
    db: AsyncSession, auth: AuthContext, payload: CopilotExecuteIn
) -> tuple[str, UUID | None, dict[str, Any], dict[str, Any], dict[str, Any]]:
    agent_id = UUID(str(payload.input["agent_id"]))
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.tenant_id != auth.tenant_id:
        raise NotFoundError(code="agent_not_found", message="智能体不存在")
    count = int(payload.input.get("count") or 5)
    topic = str(payload.input.get("topic") or agent.name)
    cases = [
        {
            "id": f"case-{index}",
            "question": f"{topic}测试问题 {index}：请说明一个关键处理要点。",
            "expectedIntent": topic,
            "expectedKeywords": [topic[:4]] if len(topic) >= 4 else [topic],
            "requireCitation": bool(payload.input.get("require_citation", True)),
            "forbiddenBehaviors": ["编造不存在的制度依据"],
            "severity": "medium",
        }
        for index in range(1, min(max(count, 1), 10) + 1)
    ]
    result = {"test_cases": cases}
    return "agent", agent.id, {}, result, result


async def handle_run_test_suite(
    db: AsyncSession, auth: AuthContext, payload: CopilotExecuteIn
) -> tuple[str, UUID | None, dict[str, Any], dict[str, Any], dict[str, Any]]:
    agent_id = UUID(str(payload.input["agent_id"]))
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.tenant_id != auth.tenant_id:
        raise NotFoundError(code="agent_not_found", message="智能体不存在")
    cases = payload.input.get("test_cases") or []
    if not isinstance(cases, list):
        raise ValidationError(code="invalid_test_cases", message="测试用例格式错误")
    results = []
    for case in cases:
        question = str((case or {}).get("question") or "")
        answer = ""
        citations = []
        usage: dict[str, Any] = {}
        tool_calls = []
        execution_succeeded = False
        failure_reasons: list[str] = []
        latency_ms: int | None = None
        if agent.status != "active":
            failure_reasons.append("智能体尚未启用，无法执行真实对话测试。")
        else:
            import time

            t0 = time.perf_counter()
            try:
                run = await dispatch_single_agent(
                    db,
                    tenant_id=auth.tenant_id,
                    user_id=auth.user_id,
                    agent_id=agent.id,
                    payload=AgentRunIn(
                        query=question,
                        workspace_id=UUID(str(payload.workspace_id)) if payload.workspace_id else None,
                        history_limit=0,
                        max_tool_rounds=1,
                    ),
                )
                latency_ms = int((time.perf_counter() - t0) * 1000)
                if run is None:
                    failure_reasons.append("智能体不存在或不可用。")
                else:
                    execution_succeeded = True
                    answer = run.answer
                    citations = [
                        {
                            "documentId": str(item.doc_id) if getattr(item, "doc_id", None) else None,
                            "title": getattr(item, "doc_name", None) or getattr(item, "source_name", None),
                            "chunkId": str(item.chunk_id) if getattr(item, "chunk_id", None) else None,
                        }
                        for item in run.citations
                    ]
                    usage = run.usage or {}
                    tool_calls = [item.tool_name for item in run.tool_results]
            except Exception as exc:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                failure_reasons.append(str(getattr(exc, "message", None) or exc))
        expected_keywords = [str(item) for item in (case or {}).get("expectedKeywords", []) if str(item).strip()]
        forbidden = [str(item) for item in (case or {}).get("forbiddenBehaviors", []) if str(item).strip()]
        keywords_matched = all(keyword in answer for keyword in expected_keywords) if expected_keywords else None
        citation_present = bool(citations)
        forbidden_triggered = any(item in answer for item in forbidden)
        if keywords_matched is False:
            failure_reasons.append("回答未包含预期关键词。")
        if (case or {}).get("requireCitation", True) and not citation_present:
            failure_reasons.append("回答缺少引用来源。")
        if forbidden_triggered:
            failure_reasons.append("回答触发禁止行为规则。")
        passed = execution_succeeded and not failure_reasons
        results.append(
            {
                "testCaseId": str((case or {}).get("id") or question[:12]),
                "question": question,
                "answer": answer,
                "citedSources": citations,
                "latencyMs": latency_ms,
                "inputTokens": usage.get("prompt_tokens") or usage.get("input_tokens"),
                "outputTokens": usage.get("completion_tokens") or usage.get("output_tokens"),
                "toolCalls": tool_calls,
                "passed": passed,
                "checks": {
                    "intentMatched": None,
                    "keywordsMatched": keywords_matched,
                    "citationPresent": citation_present,
                    "forbiddenBehaviorTriggered": forbidden_triggered,
                    "executionSucceeded": execution_succeeded,
                },
                "failureReasons": failure_reasons,
            }
        )
    passed = sum(1 for item in results if item["passed"])
    report = {"total": len(results), "passed": passed, "failed": len(results) - passed, "results": results}
    return "agent", agent.id, {}, report, {"test_report": report}


async def handle_run_preflight(
    db: AsyncSession, auth: AuthContext, payload: CopilotExecuteIn
) -> tuple[str, UUID | None, dict[str, Any], dict[str, Any], dict[str, Any]]:
    agent_id = UUID(str(payload.input["agent_id"]))
    precheck = await run_publish_precheck(db, tenant_id=auth.tenant_id, agent_id=agent_id)
    result = precheck.model_dump(mode="json")
    return "agent", agent_id, {}, result, {"preflight": result}


async def handle_publish_agent(
    db: AsyncSession, auth: AuthContext, payload: CopilotExecuteIn
) -> tuple[str, UUID | None, dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not payload.input.get("publish_confirmed"):
        raise ValidationError(code="publish_confirmation_required", message="发布需要单独二次确认")
    agent_id = UUID(str(payload.input["agent_id"]))
    before = await get_agent(db, tenant_id=auth.tenant_id, agent_id=agent_id)
    if before is None:
        raise NotFoundError(code="agent_not_found", message="智能体不存在")
    try:
        await validate_publish_confirmation(
            db,
            tenant_id=auth.tenant_id,
            agent=before,
            expected_configuration_hash=payload.input.get("configuration_hash"),
        )
    except ValueError as exc:
        raise ValidationError(code=str(exc), message="智能体配置已在确认后发生变化，请重新运行发布检查并确认。") from exc
    updated = await publish_agent(db, tenant_id=auth.tenant_id, agent_id=agent_id)
    if updated is None:
        raise NotFoundError(code="agent_not_found", message="智能体不存在")
    return "agent", updated.id, {"status": before.status}, {"status": updated.status}, {"agent": updated.model_dump(mode="json")}


async def kb_document_counts(db: AsyncSession, *, tenant_id: UUID, kb_id: UUID) -> dict[str, int]:
    result = await db.execute(
        select(Document.parse_status, func.count(Document.id))
        .where(Document.tenant_id == tenant_id, Document.kb_id == kb_id, Document.version_status == "active")
        .group_by(Document.parse_status)
    )
    rows = {str(status or "pending"): int(count) for status, count in result.all()}
    done = rows.get("done", 0)
    failed = rows.get("failed", 0)
    total = sum(rows.values())
    return {"total": total, "done": done, "failed": failed, "processing": max(total - done - failed, 0)}


def sanitize_audit_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sensitive = {"api_key", "password", "token", "secret", "authorization"}

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: "***" if key.lower() in sensitive else clean(item) for key, item in value.items()}
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return clean(payload)


register_tool(
    CopilotToolSpec(
        name="agents.create_draft",
        description="创建智能体草稿",
        category="agents",
        risk_level="L2",
        requires_confirmation=True,
        permission=("agent:publish",),
        input_schema={"required": ["name"], "properties": {"name": {"type": "string"}, "model_id": {"type": "string"}, "kb_ids": {"type": "array"}}},
        handler=handle_create_agent,
    )
)
register_tool(
    CopilotToolSpec(
        name="knowledge_bases.create",
        description="创建空知识库",
        category="knowledge_bases",
        risk_level="L2",
        requires_confirmation=True,
        permission=("kb:create",),
        input_schema={"required": ["name"], "properties": {"name": {"type": "string"}, "type": {"type": "string"}}},
        handler=handle_create_kb,
    )
)
register_tool(
    CopilotToolSpec(
        name="agents.change_model",
        description="修改智能体绑定模型",
        category="agents",
        risk_level="L2",
        requires_confirmation=True,
        permission=("agent:publish",),
        input_schema={"required": ["agent_id", "model_id"]},
        handler=handle_change_model,
    )
)
register_tool(
    CopilotToolSpec(
        name="agents.bind_knowledge",
        description="给智能体绑定知识库",
        category="agents",
        risk_level="L2",
        requires_confirmation=True,
        permission=("agent:publish",),
        input_schema={"required": ["agent_id", "kb_ids"]},
        handler=handle_bind_knowledge,
    )
)
register_tool(
    CopilotToolSpec(
        name="agents.bind_tool",
        description="给智能体绑定工具",
        category="agents",
        risk_level="L2",
        requires_confirmation=True,
        permission=("agent:publish",),
        input_schema={"required": ["agent_id", "tool_ids"]},
        handler=handle_bind_tool,
    )
)
register_tool(
    CopilotToolSpec(
        name="agents.update_prompt",
        description="修改智能体提示词",
        category="agents",
        risk_level="L2",
        requires_confirmation=True,
        permission=("agent:publish",),
        input_schema={"required": ["agent_id", "persona"]},
        handler=handle_update_prompt,
    )
)
register_tool(
    CopilotToolSpec(
        name="knowledge_bases.get_status",
        description="查询知识库处理状态",
        category="knowledge_bases",
        risk_level="L1",
        requires_confirmation=False,
        permission=("kb:create",),
        input_schema={"required": ["kb_id"]},
        handler=handle_kb_status,
    )
)
register_tool(
    CopilotToolSpec(
        name="knowledge_bases.check_readiness",
        description="检查知识库是否可用于智能体绑定和测试",
        category="knowledge_bases",
        risk_level="L1",
        requires_confirmation=False,
        permission=("kb:create",),
        input_schema={"required": ["kb_id"]},
        handler=handle_kb_check_readiness,
    )
)
register_tool(
    CopilotToolSpec(
        name="agents.generate_test_cases",
        description="生成结构化智能体测试用例",
        category="agents",
        risk_level="L1",
        requires_confirmation=False,
        permission=("agent:publish",),
        input_schema={"required": ["agent_id"]},
        handler=handle_generate_test_cases,
    )
)
register_tool(
    CopilotToolSpec(
        name="agents.run_test_suite",
        description="执行智能体测试套件",
        category="agents",
        risk_level="L2",
        requires_confirmation=True,
        permission=("agent:publish",),
        input_schema={"required": ["agent_id", "test_cases"]},
        handler=handle_run_test_suite,
    )
)
register_tool(
    CopilotToolSpec(
        name="agents.run_preflight_check",
        description="执行发布前检查",
        category="agents",
        risk_level="L1",
        requires_confirmation=False,
        permission=("agent:publish",),
        input_schema={"required": ["agent_id"]},
        handler=handle_run_preflight,
    )
)
register_tool(
    CopilotToolSpec(
        name="agents.publish",
        description="发布智能体，必须单独二次确认",
        category="agents",
        risk_level="L3",
        requires_confirmation=True,
        permission=("agent:publish",),
        input_schema={"required": ["agent_id", "publish_confirmed", "configuration_hash"]},
        handler=handle_publish_agent,
    )
)
