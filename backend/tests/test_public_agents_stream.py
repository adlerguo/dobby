import json
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import public_agents
from app.core.api_key_auth import AppApiKeyContext, get_app_api_key_context
from app.core.database import get_db
from app.core.redis import get_redis
from app.models import Agent, Conversation, Model
from app.orchestrator import runtime
from app.schemas import CitationOut, ContextBuildOut, ContextMessageOut


class FakeSession:
    def __init__(self) -> None:
        self.added = []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

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


class FakeSessionLocal:
    def __call__(self):
        return FakeSession()


def parse_sse_events(body: str) -> list[tuple[str, dict]]:
    events = []
    for frame in body.strip().split("\n\n"):
        lines = frame.splitlines()
        event = next(
            line.removeprefix("event: ").strip()
            for line in lines
            if line.startswith("event: ")
        )
        data = next(
            line.removeprefix("data: ").strip()
            for line in lines
            if line.startswith("data: ")
        )
        events.append((event, json.loads(data)))
    return events


@pytest.fixture
def public_client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, AppApiKeyContext]:
    auth = AppApiKeyContext(
        tenant_id=uuid4(),
        app_id=uuid4(),
        agent_id=uuid4(),
        key_id=uuid4(),
        user_id=uuid4(),
        config={},
    )

    async def fake_db():
        yield object()

    app = FastAPI()
    app.include_router(public_agents.router, prefix="/api/v1")
    app.dependency_overrides[get_app_api_key_context] = lambda: auth
    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_redis] = lambda: object()
    monkeypatch.setattr(public_agents, "SessionLocal", FakeSessionLocal())
    return TestClient(app), auth


def make_agent(auth: AppApiKeyContext) -> Agent:
    return Agent(
        id=auth.agent_id,
        tenant_id=auth.tenant_id,
        name="Public Agent",
        type="assistant",
        config={},
        model_id=uuid4(),
        status="active",
    )


def make_context(agent: Agent) -> ContextBuildOut:
    return ContextBuildOut(
        agent_id=agent.id,
        conversation_id=None,
        workspace_id=None,
        messages=[ContextMessageOut(role="user", content="hello", tokens=1)],
        tools=[],
        retrieved_chunks=[],
        citations=[
            CitationOut(
                chunk_id=uuid4(),
                doc_id=uuid4(),
                doc_name="doc-1",
                seq=1,
                content_length=5,
                score=0.9,
                match_channels=["vector"],
                snippet="hello",
            )
        ],
        token_budget={"max": 3500},
        truncation={},
    )


def test_public_app_chat_stream_forwards_frames_and_records_usage_once(
    public_client: tuple[TestClient, AppApiKeyContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, auth = public_client
    agent = make_agent(auth)
    expected_conversation_id = uuid4()
    calls: list[tuple[str, dict | None]] = []

    class FakeAgentRepository:
        def __init__(self, db, tenant_id) -> None:
            self.tenant_id = tenant_id

        async def get_by_id(self, agent_id):
            return agent if agent_id == agent.id else None

    async def fake_ensure_conversation(
        db,
        *,
        tenant_id,
        user_id,
        agent,
        conversation_id,
        workspace_id,
        title,
    ):
        return Conversation(
            id=conversation_id or expected_conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent.id,
            workspace_id=workspace_id,
            title=title,
        )

    async def fake_load_llm_model(db, *, tenant_id, agent, workspace_id):
        return Model(
            id=agent.model_id,
            name="mock-model",
            provider="mock",
            type="llm",
            is_active=True,
        )

    async def fake_build_agent_context(db, **kwargs):
        return make_context(agent)

    async def fake_call_maas_chat_stream(*args, **kwargs):
        yield {"type": "delta", "text": "hello"}
        yield {"type": "delta", "text": " world"}
        yield {"type": "usage", "usage": {"prompt_tokens": 3, "completion_tokens": 2}}

    async def fake_run_tool_loop(*args, max_tool_rounds, **kwargs):
        assert max_tool_rounds == 0
        return []

    async def fake_enforce_public_key_limits(redis, auth):
        calls.append(("enforce", None))

    async def fake_mark_key_used_and_record_usage(db, *, auth, usage):
        calls.append(("db_usage", usage))

    async def fake_record_public_key_usage(redis, auth, usage):
        calls.append(("redis_usage", usage))

    monkeypatch.setattr(runtime, "AgentRepository", FakeAgentRepository)
    monkeypatch.setattr(runtime, "ensure_conversation", fake_ensure_conversation)
    monkeypatch.setattr(runtime, "load_llm_model", fake_load_llm_model)
    monkeypatch.setattr(runtime, "build_agent_context", fake_build_agent_context)
    monkeypatch.setattr(runtime, "call_maas_chat_stream", fake_call_maas_chat_stream)
    monkeypatch.setattr(runtime, "run_tool_loop", fake_run_tool_loop)
    monkeypatch.setattr(
        public_agents, "enforce_public_key_limits", fake_enforce_public_key_limits
    )
    monkeypatch.setattr(
        public_agents,
        "mark_key_used_and_record_usage",
        fake_mark_key_used_and_record_usage,
    )
    monkeypatch.setattr(
        public_agents, "record_public_key_usage", fake_record_public_key_usage
    )

    response = client.post(
        f"/api/v1/public/apps/{auth.app_id}/chat",
        json={"query": "hello", "stream": True},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    events = parse_sse_events(response.text)
    event_names = [event for event, _data in events]
    assert event_names == ["citation", "delta", "delta", "done"]
    citation = events[0][1]
    assert {
        "chunk_id": citation["chunk_id"],
        "doc_id": citation["doc_id"],
        "doc_name": citation["doc_name"],
        "seq": citation["seq"],
        "content_length": citation["content_length"],
        "score": citation["score"],
        "vector_score": citation["vector_score"],
        "text_score": citation["text_score"],
        "match_channels": citation["match_channels"],
        "snippet": citation["snippet"],
    } == {
        "chunk_id": citation["chunk_id"],
        "doc_id": citation["doc_id"],
        "doc_name": "doc-1",
        "seq": 1,
        "content_length": 5,
        "score": 0.9,
        "vector_score": None,
        "text_score": None,
        "match_channels": ["vector"],
        "snippet": "hello",
    }
    assert "source_name" in citation
    assert "page_start" in citation
    assert events[1] == ("delta", {"text": "hello"})
    assert events[2] == ("delta", {"text": " world"})
    assert events[3][1]["conversation_id"] == str(expected_conversation_id)
    assert events[3][1]["citation_count"] == 1
    assert events[-1][1]["usage"] == {"prompt_tokens": 3, "completion_tokens": 2}
    assert calls == [
        ("enforce", None),
        ("db_usage", {"prompt_tokens": 3, "completion_tokens": 2}),
        ("redis_usage", {"prompt_tokens": 3, "completion_tokens": 2}),
    ]
