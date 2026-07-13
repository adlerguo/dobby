from collections import Counter
from datetime import UTC, datetime, timedelta
from statistics import mean
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, Conversation, Message, RunTrace
from app.schemas import (
    DashboardExecutiveOut,
    DashboardMetricOut,
    DashboardOverviewOut,
    DashboardTechnicalOut,
    TraceDetailOut,
    TraceSpanOut,
)


async def build_dashboard_overview(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    view: str,
    period_days: int,
) -> DashboardOverviewOut:
    snapshot = await load_observability_snapshot(db, tenant_id=tenant_id, period_days=period_days)
    technical = make_technical_summary(snapshot)
    executive = make_executive_summary(snapshot)
    metrics = [
        DashboardMetricOut(key="conversations", label="会话数", value=snapshot["conversation_count"], unit="次"),
        DashboardMetricOut(key="agent_runs", label="智能体运行", value=snapshot["run_count"], unit="次"),
        DashboardMetricOut(key="success_rate", label="成功率", value=technical["success_rate"], unit="%"),
        DashboardMetricOut(key="avg_latency_ms", label="平均耗时", value=technical["avg_latency_ms"], unit="ms"),
        DashboardMetricOut(key="total_tokens", label="Token 消耗", value=technical["total_tokens"], unit="tokens"),
        DashboardMetricOut(key="tool_calls", label="工具调用", value=technical["tool_calls"], unit="次"),
        DashboardMetricOut(key="cited_answers", label="带引用回答", value=executive["cited_answers"], unit="条"),
    ]
    return DashboardOverviewOut(
        view=view,
        period_days=period_days,
        generated_at=datetime.now(UTC),
        metrics=metrics,
        highlights=make_highlights(snapshot, technical, executive, view=view),
        technical=technical,
        executive=executive,
    )


async def build_technical_dashboard(db: AsyncSession, *, tenant_id: UUID, period_days: int) -> DashboardTechnicalOut:
    snapshot = await load_observability_snapshot(db, tenant_id=tenant_id, period_days=period_days)
    traces = snapshot["traces"]
    root_traces = snapshot["root_traces"]
    latencies = [trace.latency_ms or 0 for trace in root_traces if trace.latency_ms is not None]
    summary = make_technical_summary(snapshot)
    return DashboardTechnicalOut(
        period_days=period_days,
        generated_at=datetime.now(UTC),
        summary=summary,
        spans_by_type=dict(Counter(trace.span_type or "unknown" for trace in traces)),
        spans_by_status=dict(Counter(trace.status or "unknown" for trace in traces)),
        latency={
            "avg_ms": summary["avg_latency_ms"],
            "p95_ms": percentile(latencies, 95),
            "max_ms": max(latencies) if latencies else None,
        },
        token_usage={
            "total": summary["total_tokens"],
            "avg_per_run": int(summary["total_tokens"] / summary["run_count"]) if summary["run_count"] else 0,
        },
        top_agents=top_agents(snapshot),
        recent_errors=recent_errors(snapshot),
        recent_runs=recent_runs(snapshot),
    )


async def build_executive_dashboard(db: AsyncSession, *, tenant_id: UUID, period_days: int) -> DashboardExecutiveOut:
    snapshot = await load_observability_snapshot(db, tenant_id=tenant_id, period_days=period_days)
    executive = make_executive_summary(snapshot)
    technical = make_technical_summary(snapshot)
    scorecards = [
        DashboardMetricOut(key="service_count", label="服务次数", value=snapshot["run_count"], unit="次", description="智能体完成的一轮服务"),
        DashboardMetricOut(key="success_rate", label="服务稳定性", value=technical["success_rate"], unit="%", description="成功完成比例"),
        DashboardMetricOut(key="knowledge_answers", label="知识问答", value=executive["cited_answers"], unit="条", description="带知识出处的回答"),
        DashboardMetricOut(key="data_answers", label="智能问数", value=executive["data_answers"], unit="次", description="自动查询数据表的回答"),
        DashboardMetricOut(key="active_agents", label="上线智能体", value=executive["active_agents"], unit="个", description="当前可用的智能体"),
    ]
    return DashboardExecutiveOut(
        period_days=period_days,
        generated_at=datetime.now(UTC),
        headline=make_headline(snapshot, technical, executive),
        scorecards=scorecards,
        business_mix=business_mix(snapshot),
        adoption=top_agents(snapshot),
        takeaways=make_highlights(snapshot, technical, executive, view="executive"),
    )


async def build_trace_detail(db: AsyncSession, *, tenant_id: UUID, cid: UUID) -> TraceDetailOut | None:
    trace = await db.get(RunTrace, cid)
    conversation_id = cid
    root_trace_id = None
    if trace is not None and trace.tenant_id == tenant_id:
        conversation_id = trace.conversation_id or cid
        root_trace_id = trace.id if trace.span_type == "agent" else trace.parent_id

    conversation = await db.get(Conversation, conversation_id)
    if conversation is not None and conversation.tenant_id != tenant_id:
        return None

    trace_stmt = select(RunTrace).where(RunTrace.tenant_id == tenant_id)
    if conversation is not None:
        trace_stmt = trace_stmt.where(RunTrace.conversation_id == conversation.id)
    elif trace is not None and trace.tenant_id == tenant_id:
        root_id = root_trace_id or trace.id
        trace_stmt = trace_stmt.where((RunTrace.id == root_id) | (RunTrace.parent_id == root_id))
    else:
        return None

    traces = list((await db.execute(trace_stmt.order_by(RunTrace.created_at.asc()))).scalars().all())
    if not traces:
        return None
    agents = await load_agents(db, tenant_id)
    messages = []
    if conversation is not None:
        result = await db.execute(
            select(Message)
            .where(Message.tenant_id == tenant_id, Message.conversation_id == conversation.id)
            .order_by(Message.created_at.asc())
        )
        for message in result.scalars().all():
            messages.append(
                {
                    "id": str(message.id),
                    "role": message.role,
                    "content": message.content,
                    "tokens": message.tokens,
                    "citations": message.citations or [],
                    "created_at": message.created_at.isoformat(),
                }
            )

    root = next((item for item in traces if item.span_type == "agent"), traces[0])
    spans = [
        TraceSpanOut(
            id=item.id,
            parent_id=item.parent_id,
            conversation_id=item.conversation_id,
            agent_id=item.agent_id,
            agent_name=agents.get(item.agent_id),
            span_type=item.span_type,
            name=item.name,
            status=item.status,
            input=item.input,
            output=item.output,
            tokens=item.tokens,
            latency_ms=item.latency_ms,
            created_at=item.created_at,
        )
        for item in traces
    ]
    return TraceDetailOut(
        id=root.id,
        tenant_id=tenant_id,
        conversation_id=conversation.id if conversation is not None else None,
        title=conversation.title if conversation is not None else None,
        root_trace_id=root.id,
        status=root.status,
        summary={
            "span_count": len(spans),
            "message_count": len(messages),
            "total_tokens": sum(item.tokens or 0 for item in traces),
            "total_latency_ms": root.latency_ms,
            "has_tool_call": any(item.span_type == "tool" for item in traces),
            "has_error": any(item.status == "failed" for item in traces),
        },
        spans=spans,
        messages=messages,
    )


async def load_observability_snapshot(db: AsyncSession, *, tenant_id: UUID, period_days: int) -> dict:
    since = datetime.now(UTC) - timedelta(days=period_days)
    traces = list(
        (
            await db.execute(
                select(RunTrace).where(RunTrace.tenant_id == tenant_id, RunTrace.created_at >= since)
            )
        )
        .scalars()
        .all()
    )
    root_traces = [trace for trace in traces if trace.span_type == "agent"]
    conversations = list(
        (
            await db.execute(
                select(Conversation).where(Conversation.tenant_id == tenant_id, Conversation.created_at >= since)
            )
        )
        .scalars()
        .all()
    )
    messages = list(
        (
            await db.execute(select(Message).where(Message.tenant_id == tenant_id, Message.created_at >= since))
        )
        .scalars()
        .all()
    )
    agents = await load_agents(db, tenant_id)
    active_agents = list(
        (
            await db.execute(select(Agent).where(Agent.tenant_id == tenant_id, Agent.status == "active"))
        )
        .scalars()
        .all()
    )
    return {
        "since": since,
        "traces": traces,
        "root_traces": root_traces,
        "run_count": len(root_traces),
        "conversations": conversations,
        "conversation_count": len(conversations),
        "messages": messages,
        "agents": agents,
        "active_agents": active_agents,
    }


async def load_agents(db: AsyncSession, tenant_id: UUID) -> dict[UUID, str]:
    result = await db.execute(select(Agent).where(Agent.tenant_id == tenant_id))
    return {agent.id: agent.name for agent in result.scalars().all()}


def make_technical_summary(snapshot: dict) -> dict:
    root_traces = snapshot["root_traces"]
    run_count = len(root_traces)
    failed_count = sum(1 for trace in root_traces if trace.status == "failed")
    success_count = run_count - failed_count
    latencies = [trace.latency_ms or 0 for trace in root_traces if trace.latency_ms is not None]
    total_tokens = sum(trace.tokens or 0 for trace in root_traces)
    tool_calls = sum(1 for trace in snapshot["traces"] if trace.span_type == "tool")
    model_calls = sum(1 for trace in snapshot["traces"] if trace.span_type == "model")
    return {
        "run_count": run_count,
        "success_count": success_count,
        "failed_count": failed_count,
        "success_rate": round((success_count / run_count) * 100, 2) if run_count else 100.0,
        "avg_latency_ms": int(mean(latencies)) if latencies else 0,
        "p95_latency_ms": percentile(latencies, 95),
        "total_tokens": total_tokens,
        "tool_calls": tool_calls,
        "model_calls": model_calls,
    }


def make_executive_summary(snapshot: dict) -> dict:
    cited_answers = sum(1 for message in snapshot["messages"] if message.role == "assistant" and message.citations)
    data_answers = 0
    for trace in snapshot["root_traces"]:
        output = trace.output or {}
        if output.get("tool_results"):
            data_answers += 1
    return {
        "active_agents": len(snapshot["active_agents"]),
        "cited_answers": cited_answers,
        "data_answers": data_answers,
        "conversation_count": snapshot["conversation_count"],
    }


def make_highlights(snapshot: dict, technical: dict, executive: dict, *, view: str) -> list[str]:
    if view == "executive":
        return [
            f"近 {period_label(snapshot)} 已完成 {technical['run_count']} 次智能体服务。",
            f"服务稳定性为 {technical['success_rate']}%。",
            f"知识问答产生 {executive['cited_answers']} 条带出处回答，智能问数完成 {executive['data_answers']} 次数据查询。",
        ]
    return [
        f"Root run {technical['run_count']} 次，model span {technical['model_calls']} 次，tool span {technical['tool_calls']} 次。",
        f"P95 延迟 {technical['p95_latency_ms']} ms，平均延迟 {technical['avg_latency_ms']} ms。",
        f"累计 token {technical['total_tokens']}，失败 root run {technical['failed_count']} 次。",
    ]


def period_label(snapshot: dict) -> str:
    delta = datetime.now(UTC) - snapshot["since"]
    return f"{max(delta.days, 1)} 天"


def top_agents(snapshot: dict) -> list[dict]:
    counts = Counter(trace.agent_id for trace in snapshot["root_traces"] if trace.agent_id is not None)
    agents = snapshot["agents"]
    return [
        {"agent_id": str(agent_id), "agent_name": agents.get(agent_id, "未知智能体"), "runs": runs}
        for agent_id, runs in counts.most_common(8)
    ]


def business_mix(snapshot: dict) -> list[dict]:
    counts = Counter()
    for trace in snapshot["root_traces"]:
        output = trace.output or {}
        if output.get("tool_results"):
            counts["智能问数/工具"] += 1
        elif output.get("citations"):
            counts["知识问答"] += 1
        else:
            counts["通用问答"] += 1
    total = sum(counts.values()) or 1
    return [{"name": name, "count": count, "ratio": round(count / total * 100, 2)} for name, count in counts.items()]


def recent_errors(snapshot: dict) -> list[dict]:
    errors = [trace for trace in snapshot["traces"] if trace.status == "failed"]
    errors.sort(key=lambda item: item.created_at, reverse=True)
    return [
        {
            "trace_id": str(trace.id),
            "conversation_id": str(trace.conversation_id) if trace.conversation_id else None,
            "span_type": trace.span_type,
            "name": trace.name,
            "output": trace.output,
            "created_at": trace.created_at.isoformat(),
        }
        for trace in errors[:10]
    ]


def recent_runs(snapshot: dict) -> list[dict]:
    roots = sorted(snapshot["root_traces"], key=lambda item: item.created_at, reverse=True)
    agents = snapshot["agents"]
    return [
        {
            "trace_id": str(trace.id),
            "conversation_id": str(trace.conversation_id) if trace.conversation_id else None,
            "agent_id": str(trace.agent_id) if trace.agent_id else None,
            "agent_name": agents.get(trace.agent_id, "未知智能体"),
            "status": trace.status,
            "latency_ms": trace.latency_ms,
            "tokens": trace.tokens,
            "created_at": trace.created_at.isoformat(),
        }
        for trace in roots[:20]
    ]


def make_headline(snapshot: dict, technical: dict, executive: dict) -> str:
    return (
        f"近 {period_label(snapshot)} 平台完成 {technical['run_count']} 次智能体服务，"
        f"成功率 {technical['success_rate']}%，当前上线 {executive['active_agents']} 个智能体。"
    )


def percentile(values: list[int], percent: int) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((percent / 100) * (len(ordered) - 1))))
    return int(ordered[index])
