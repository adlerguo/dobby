import asyncio
import os
from uuid import uuid4

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("MAAS_ADMIN_TOKEN", "test-token")

from app.models import Agent, Conversation, Model, RunTrace, Tool  # noqa: E402
from app.orchestrator import runtime  # noqa: E402
from app.schemas import (  # noqa: E402
    AgentRunIn,
    ContextBuildOut,
    ContextMessageOut,
    ContextToolOut,
    RuntimeToolCallIn,
)
import app.services.tool_service as tool_service  # noqa: E402


TENANT_ID = uuid4()
USER_ID = uuid4()


class FakeDB:
    def __init__(self) -> None:
        self.added = []
        self.commits = 0

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if hasattr(obj, "id") and getattr(obj, "id", None) is None:
                setattr(obj, "id", uuid4())

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj) -> None:
        if hasattr(obj, "id") and getattr(obj, "id", None) is None:
            setattr(obj, "id", uuid4())

    async def get(self, model, id_):
        return None

    @property
    def traces(self) -> list[RunTrace]:
        return [obj for obj in self.added if isinstance(obj, RunTrace)]


def run_async(awaitable):
    return asyncio.run(awaitable)


async def collect_events(generator):
    events = []
    async for event in generator:
        events.append(event)
    return events


def make_agent(*, agent_type: str = "assistant") -> Agent:
    return Agent(
        id=uuid4(),
        tenant_id=TENANT_ID,
        name="Smoke Agent",
        type=agent_type,
        config={},
        model_id=uuid4(),
        status="active",
    )


def make_model() -> Model:
    return Model(id=uuid4(), name="mock-model", provider="mock", type="llm", is_active=True)


def make_tool(*, tool_type: str = "builtin", name: str = "echo", config: dict | None = None) -> Tool:
    return Tool(
        id=uuid4(),
        tenant_id=TENANT_ID,
        name=name,
        type=tool_type,
        schema={"type": "object"},
        config=config or {"builtin": name},
        status="active",
    )


def make_context(agent: Agent, *, tools: list[Tool] | None = None) -> ContextBuildOut:
    return ContextBuildOut(
        agent_id=agent.id,
        conversation_id=None,
        workspace_id=None,
        messages=[ContextMessageOut(role="user", content="请调用工具", tokens=4)],
        tools=[
            ContextToolOut(id=tool.id, name=tool.name, type=tool.type, tool_schema=tool.schema or {})
            for tool in (tools or [])
        ],
        retrieved_chunks=[],
        citations=[],
        token_budget={"max": 3500},
        truncation={},
    )


def install_repositories(monkeypatch: pytest.MonkeyPatch, *, agents: dict, tools: dict) -> None:
    class FakeAgentRepository:
        def __init__(self, db, tenant_id) -> None:
            self.tenant_id = tenant_id

        async def get_by_id(self, agent_id):
            return agents.get(agent_id)

    class FakeToolRepository:
        def __init__(self, db, tenant_id) -> None:
            self.tenant_id = tenant_id

        async def get_by_id(self, tool_id):
            return tools.get(tool_id)

    monkeypatch.setattr(runtime, "AgentRepository", FakeAgentRepository)
    monkeypatch.setattr(runtime, "ToolRepository", FakeToolRepository)
    monkeypatch.setattr(tool_service, "ToolRepository", FakeToolRepository)


def install_agent_baseline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    agent: Agent,
    context: ContextBuildOut,
    model: Model | None = None,
) -> None:
    selected_model = model or make_model()

    async def fake_ensure_conversation(db, *, tenant_id, user_id, agent, conversation_id, workspace_id, title):
        return Conversation(
            id=conversation_id or uuid4(),
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent.id,
            workspace_id=workspace_id,
            title=title,
        )

    async def fake_load_llm_model(db, *, tenant_id, agent, workspace_id):
        return selected_model

    async def fake_build_agent_context(db, **kwargs):
        return context

    monkeypatch.setattr(runtime, "ensure_conversation", fake_ensure_conversation)
    monkeypatch.setattr(runtime, "load_llm_model", fake_load_llm_model)
    monkeypatch.setattr(runtime, "build_agent_context", fake_build_agent_context)


def chat_response(content: str, *, prompt_tokens: int = 1, completion_tokens: int = 1) -> dict:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


def test_non_stream_agent_with_bound_tool_returns_tool_output(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = make_agent()
    tool = make_tool()
    db = FakeDB()
    install_repositories(monkeypatch, agents={agent.id: agent}, tools={tool.id: tool})
    install_agent_baseline(monkeypatch, agent=agent, context=make_context(agent, tools=[tool]))

    async def fake_call_maas_chat(db, *args, name="maas_chat", **kwargs):
        return chat_response("最终回答" if name == "maas_final" else "准备调用工具")

    monkeypatch.setattr(runtime, "call_maas_chat", fake_call_maas_chat)

    result = run_async(
        runtime.run_agent(
            db,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            agent_id=agent.id,
            payload=AgentRunIn(
                query="请调用工具",
                tool_calls=[RuntimeToolCallIn(tool_id=tool.id, input={"payload": "ok"})],
            ),
        )
    )

    assert result is not None
    assert result.answer == "最终回答"
    assert result.tool_results[0].status == "ok"
    assert result.tool_results[0].output == {"value": {"payload": "ok"}}
    assert db.commits == 1


def test_stream_agent_with_bound_tool_ends_with_done(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = make_agent()
    tool = make_tool()
    db = FakeDB()
    install_repositories(monkeypatch, agents={agent.id: agent}, tools={tool.id: tool})
    install_agent_baseline(monkeypatch, agent=agent, context=make_context(agent, tools=[tool]))

    async def fake_call_maas_chat_stream(*args, **kwargs):
        yield {"type": "delta", "text": "准备调用工具"}
        yield {"type": "usage", "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    async def fake_call_maas_chat(*args, **kwargs):
        return chat_response("最终回答")

    monkeypatch.setattr(runtime, "call_maas_chat_stream", fake_call_maas_chat_stream)
    monkeypatch.setattr(runtime, "call_maas_chat", fake_call_maas_chat)

    events = run_async(
        collect_events(
            runtime.stream_agent_events(
                db,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                agent_id=agent.id,
                payload=AgentRunIn(
                    query="请调用工具",
                    tool_calls=[RuntimeToolCallIn(tool_id=tool.id, input={"payload": "ok"})],
                ),
            )
        )
    )

    assert [event["event"] for event in events][-1] == "done"
    assert events[-1]["data"]["tool_results"][0]["status"] == "ok"
    assert db.commits == 1


def test_non_stream_tool_exception_returns_structured_error(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = make_agent()
    tool = make_tool()
    db = FakeDB()
    install_repositories(monkeypatch, agents={agent.id: agent}, tools={tool.id: tool})
    install_agent_baseline(monkeypatch, agent=agent, context=make_context(agent, tools=[tool]))

    async def fake_call_maas_chat(*args, **kwargs):
        return chat_response("准备调用工具")

    async def failing_run_tool(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(runtime, "call_maas_chat", fake_call_maas_chat)
    monkeypatch.setattr(runtime, "run_tool", failing_run_tool)

    result = run_async(
        runtime.run_agent(
            db,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            agent_id=agent.id,
            payload=AgentRunIn(
                query="请调用工具",
                tool_calls=[RuntimeToolCallIn(tool_id=tool.id, input={})],
            ),
        )
    )

    assert result.tool_results[0].status == "failed"
    assert result.tool_results[0].output["error"] == "tool_execution_failed"
    assert "boom" in result.tool_results[0].output["detail"]
    assert result.answer.startswith("工具 echo 执行失败")
    assert db.traces[0].status == "failed"


def test_stream_tool_exception_currently_closes_with_done(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = make_agent()
    tool = make_tool()
    db = FakeDB()
    install_repositories(monkeypatch, agents={agent.id: agent}, tools={tool.id: tool})
    install_agent_baseline(monkeypatch, agent=agent, context=make_context(agent, tools=[tool]))

    async def fake_call_maas_chat_stream(*args, **kwargs):
        yield {"type": "delta", "text": "准备调用工具"}

    async def failing_run_tool(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(runtime, "call_maas_chat_stream", fake_call_maas_chat_stream)
    monkeypatch.setattr(runtime, "run_tool", failing_run_tool)

    events = run_async(
        collect_events(
            runtime.stream_agent_events(
                db,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                agent_id=agent.id,
                payload=AgentRunIn(
                    query="请调用工具",
                    tool_calls=[RuntimeToolCallIn(tool_id=tool.id, input={})],
                ),
            )
        )
    )

    assert events[-1]["event"] == "done"
    assert events[-1]["data"]["tool_results"][0]["status"] == "failed"
    assert any(event["event"] == "delta" and "工具 echo 执行失败" in event["data"]["text"] for event in events)


@pytest.mark.xfail(
    reason="5a baseline: stream tool exceptions currently surface as a failure delta, not an SSE error event.",
    strict=True,
)
def test_stream_tool_exception_should_emit_error_event_before_done(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = make_agent()
    tool = make_tool()
    db = FakeDB()
    install_repositories(monkeypatch, agents={agent.id: agent}, tools={tool.id: tool})
    install_agent_baseline(monkeypatch, agent=agent, context=make_context(agent, tools=[tool]))

    async def fake_call_maas_chat_stream(*args, **kwargs):
        yield {"type": "delta", "text": "准备调用工具"}

    async def failing_run_tool(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(runtime, "call_maas_chat_stream", fake_call_maas_chat_stream)
    monkeypatch.setattr(runtime, "run_tool", failing_run_tool)

    events = run_async(
        collect_events(
            runtime.stream_agent_events(
                db,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                agent_id=agent.id,
                payload=AgentRunIn(
                    query="请调用工具",
                    tool_calls=[RuntimeToolCallIn(tool_id=tool.id, input={})],
                ),
            )
        )
    )

    assert events[-1]["event"] == "done"
    assert any(event["event"] == "error" for event in events)


def test_tool_not_bound_or_missing_returns_failed_tool_result(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = make_agent()
    bound_tool = make_tool()
    missing_tool_id = uuid4()
    db = FakeDB()
    install_repositories(monkeypatch, agents={agent.id: agent}, tools={})

    unbound_result = run_async(
        runtime.run_tool_loop(
            db,
            tenant_id=TENANT_ID,
            conversation_id=uuid4(),
            agent=agent,
            parent_trace_id=uuid4(),
            context=make_context(agent, tools=[]),
            assistant_text="",
            requested_tool_calls=[RuntimeToolCallIn(tool_id=missing_tool_id, input={})],
            max_tool_rounds=1,
        )
    )
    missing_result = run_async(
        runtime.run_tool_loop(
            db,
            tenant_id=TENANT_ID,
            conversation_id=uuid4(),
            agent=agent,
            parent_trace_id=uuid4(),
            context=make_context(agent, tools=[bound_tool]),
            assistant_text="",
            requested_tool_calls=[RuntimeToolCallIn(tool_id=bound_tool.id, input={})],
            max_tool_rounds=1,
        )
    )

    assert unbound_result[0].status == "failed"
    assert unbound_result[0].output["error"] == "tool_not_bound"
    assert missing_result[0].status == "failed"
    assert missing_result[0].output["error"] == "tool_not_found"


def test_code_tool_denied_consistently_for_orchestrator_and_direct_run(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = make_agent()
    code_tool = make_tool(tool_type="code", name="python", config={"code": "print('blocked')"})
    db = FakeDB()
    install_repositories(monkeypatch, agents={agent.id: agent}, tools={code_tool.id: code_tool})
    monkeypatch.setattr(tool_service.settings, "enable_auto_code_tools", False)
    monkeypatch.setattr(tool_service.settings, "code_tool_allowlist", "")

    direct = run_async(tool_service.run_tool(db, tenant_id=TENANT_ID, tool_id=code_tool.id, input={}))
    via_orchestrator = run_async(
        runtime.run_tool_loop(
            db,
            tenant_id=TENANT_ID,
            conversation_id=uuid4(),
            agent=agent,
            parent_trace_id=uuid4(),
            context=make_context(agent, tools=[code_tool]),
            assistant_text="",
            requested_tool_calls=[RuntimeToolCallIn(tool_id=code_tool.id, input={})],
            max_tool_rounds=1,
        )
    )[0]

    assert direct.status == "failed"
    assert direct.output["error"] == "forbidden"
    assert via_orchestrator.status == "failed"
    assert via_orchestrator.output["error"] == direct.output["error"]


def test_code_tool_allowed_consistently_for_orchestrator_and_direct_run(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = make_agent()
    code_tool = make_tool(tool_type="code", name="python", config={"code": "print('ok')"})
    db = FakeDB()
    install_repositories(monkeypatch, agents={agent.id: agent}, tools={code_tool.id: code_tool})
    monkeypatch.setattr(tool_service.settings, "enable_auto_code_tools", True)

    async def fake_run_code_tool(tool, input):
        return {"stdout": "ok"}

    monkeypatch.setattr(tool_service, "run_code_tool", fake_run_code_tool)

    direct = run_async(tool_service.run_tool(db, tenant_id=TENANT_ID, tool_id=code_tool.id, input={}))
    via_orchestrator = run_async(
        runtime.run_tool_loop(
            db,
            tenant_id=TENANT_ID,
            conversation_id=uuid4(),
            agent=agent,
            parent_trace_id=uuid4(),
            context=make_context(agent, tools=[code_tool]),
            assistant_text="",
            requested_tool_calls=[RuntimeToolCallIn(tool_id=code_tool.id, input={})],
            max_tool_rounds=1,
        )
    )[0]

    assert direct.status == "ok"
    assert direct.output == {"stdout": "ok"}
    assert via_orchestrator.status == "ok"
    assert via_orchestrator.output == direct.output


def test_stream_model_failure_commits_failed_trace_and_done(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = make_agent()
    db = FakeDB()
    install_repositories(monkeypatch, agents={agent.id: agent}, tools={})
    install_agent_baseline(monkeypatch, agent=agent, context=make_context(agent))

    async def failing_call_maas_chat_stream(*args, **kwargs):
        raise ValueError("maas_timeout")
        yield

    monkeypatch.setattr(runtime, "call_maas_chat_stream", failing_call_maas_chat_stream)

    events = run_async(
        collect_events(
            runtime.stream_agent_events(
                db,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                agent_id=agent.id,
                payload=AgentRunIn(query="模型失败"),
            )
        )
    )

    assert [event["event"] for event in events] == ["error", "done"]
    assert events[-1]["data"]["status"] == "failed"
    assert db.commits == 1
    assert db.traces[0].status == "failed"
    assert db.traces[0].output == {"error": "maas_timeout"}


@pytest.mark.xfail(
    reason="D5: non-stream model failure path currently does not commit failed trace; expected to be fixed in batch 5b.",
    strict=True,
)
def test_non_stream_model_failure_should_commit_failed_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = make_agent()
    db = FakeDB()
    install_repositories(monkeypatch, agents={agent.id: agent}, tools={})
    install_agent_baseline(monkeypatch, agent=agent, context=make_context(agent))

    async def failing_call_maas_chat(*args, **kwargs):
        raise ValueError("maas_timeout")

    monkeypatch.setattr(runtime, "call_maas_chat", failing_call_maas_chat)

    try:
        run_async(
            runtime.run_agent(
                db,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                agent_id=agent.id,
                payload=AgentRunIn(query="模型失败"),
            )
        )
    except ValueError:
        pass

    assert db.commits == 1
    assert db.traces[0].status == "failed"
    assert db.traces[0].output == {"error": "maas_timeout"}
