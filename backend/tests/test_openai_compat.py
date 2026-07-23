import json
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("MAAS_ADMIN_TOKEN", "test-token")

from app.api.v1 import openai_compat
from app.core.api_key_auth import get_app_api_key_context
from app.core.database import get_db
from app.core.redis import get_redis
from app.models import Agent, AppApiKey, PublishedApp
from app.services.publish_service import hash_api_key


class FakeScalarResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDB:
    def __init__(self, *, key: AppApiKey, app: PublishedApp, agent: Agent) -> None:
        self.key = key
        self.app = app
        self.agent = agent
        self.added = []
        self.commits = 0

    async def execute(self, stmt):
        return FakeScalarResult(self.key)

    async def get(self, model, id_):
        if model is AppApiKey and id_ == self.key.id:
            return self.key
        if model is PublishedApp and id_ == self.app.id:
            return self.app
        if model is Agent and id_ == self.agent.id:
            return self.agent
        return None

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


class FakeSessionLocal:
    def __init__(self, session: FakeDB) -> None:
        self.session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture
def openai_client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, SimpleNamespace]:
    tenant_id = uuid4()
    app_id = uuid4()
    agent_id = uuid4()
    user_id = uuid4()
    raw_key = "sk-test-openai-compatible"
    key = AppApiKey(
        id=uuid4(),
        tenant_id=tenant_id,
        app_id=app_id,
        key_hash=hash_api_key(raw_key),
        status="active",
        config={},
        created_by=user_id,
    )
    app_model = PublishedApp(
        id=app_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        name="Public App",
        status="published",
        publish_type="api",
        config={},
        created_by=user_id,
    )
    agent = Agent(
        id=agent_id,
        tenant_id=tenant_id,
        name="Public Agent",
        type="assistant",
        config={},
        model_id=uuid4(),
        status="active",
    )
    db = FakeDB(key=key, app=app_model, agent=agent)
    calls: list[tuple[str, dict | None]] = []

    async def fake_db():
        yield db

    async def fake_enforce_public_key_limits(redis, auth):
        calls.append(("enforce", None))

    async def fake_mark_key_used_and_record_usage(db, *, auth, usage):
        calls.append(("db_usage", usage))

    async def fake_record_public_key_usage(redis, auth, usage):
        calls.append(("redis_usage", usage))

    app = FastAPI()
    app.include_router(openai_compat.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_redis] = lambda: object()
    monkeypatch.setattr(
        openai_compat, "enforce_public_key_limits", fake_enforce_public_key_limits
    )
    monkeypatch.setattr(
        openai_compat,
        "mark_key_used_and_record_usage",
        fake_mark_key_used_and_record_usage,
    )
    monkeypatch.setattr(
        openai_compat, "record_public_key_usage", fake_record_public_key_usage
    )
    monkeypatch.setattr(openai_compat, "SessionLocal", FakeSessionLocal(db))
    return TestClient(app), SimpleNamespace(
        auth_header={"Authorization": f"Bearer {raw_key}"}, app_id=app_id, calls=calls
    )


def parse_openai_sse(body: str) -> list[dict | str]:
    chunks: list[dict | str] = []
    for frame in body.strip().split("\n\n"):
        data = frame.removeprefix("data: ").strip()
        chunks.append("[DONE]" if data == "[DONE]" else json.loads(data))
    return chunks


def test_openai_compat_non_stream_response_and_bearer_auth(
    openai_client: tuple[TestClient, SimpleNamespace],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, context = openai_client

    async def fake_dispatch_single_agent(db, *, tenant_id, user_id, agent_id, payload):
        assert (
            payload.query
            == "历史:\n用户: old question\n助手: old answer\n\n当前问题:\nnew question"
        )
        assert payload.max_tokens == 256
        assert payload.max_tool_rounds == 0
        return SimpleNamespace(
            answer="final answer",
            usage={"prompt_tokens": 7, "completion_tokens": 3},
            citations=[],
            conversation_id=uuid4(),
            trace_id=uuid4(),
        )

    monkeypatch.setattr(
        openai_compat, "dispatch_single_agent", fake_dispatch_single_agent
    )

    missing_auth = client.post(
        f"/api/v1/public/apps/{context.app_id}/openai/v1/chat/completions",
        json={
            "model": "client-only-model",
            "messages": [{"role": "user", "content": "new question"}],
        },
    )
    response = client.post(
        f"/api/v1/public/apps/{context.app_id}/openai/v1/chat/completions",
        headers=context.auth_header,
        json={
            "model": "client-only-model",
            "messages": [
                {"role": "user", "content": "old question"},
                {"role": "assistant", "content": "old answer"},
                {"role": "user", "content": "new question"},
            ],
            "max_tokens": 1,
        },
    )

    assert missing_auth.status_code == 401
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == "client-only-model"
    assert body["choices"][0]["message"] == {
        "role": "assistant",
        "content": "final answer",
    }
    assert body["usage"] == {
        "prompt_tokens": 7,
        "completion_tokens": 3,
        "total_tokens": 10,
    }
    assert context.calls == [
        ("enforce", None),
        ("db_usage", {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}),
        (
            "redis_usage",
            {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        ),
    ]


def test_openai_compat_rejects_app_id_mismatch(
    openai_client: tuple[TestClient, SimpleNamespace],
) -> None:
    client, context = openai_client

    response = client.post(
        f"/api/v1/public/apps/{uuid4()}/openai/v1/chat/completions",
        headers=context.auth_header,
        json={"model": "ignored", "messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "app_forbidden"


def test_openai_compat_stream_frames_and_once_accounting(
    openai_client: tuple[TestClient, SimpleNamespace],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, context = openai_client

    async def fake_stream_agent_events(db, *, tenant_id, user_id, agent_id, payload):
        assert payload.max_tool_rounds == 0
        yield {"event": "citation", "data": {"ignored": True}}
        yield {"event": "delta", "data": {"text": "hello"}}
        yield {"event": "delta", "data": {"text": " world"}}
        yield {
            "event": "done",
            "data": {"usage": {"prompt_tokens": 2, "completion_tokens": 4}},
        }

    monkeypatch.setattr(
        openai_compat, "run_stream_agent_events", fake_stream_agent_events
    )

    response = client.post(
        f"/api/v1/public/apps/{context.app_id}/openai/v1/chat/completions",
        headers=context.auth_header,
        json={
            "model": "echo-model-name",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
            "stream_options": {"include_usage": True},
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    chunks = parse_openai_sse(response.text)
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert chunks[1]["choices"][0]["delta"] == {"content": "hello"}
    assert chunks[2]["choices"][0]["delta"] == {"content": " world"}
    assert chunks[3]["choices"][0]["finish_reason"] == "stop"
    assert chunks[4]["choices"] == []
    assert chunks[4]["usage"] == {
        "prompt_tokens": 2,
        "completion_tokens": 4,
        "total_tokens": 6,
    }
    assert chunks[5] == "[DONE]"
    assert all(
        chunk == "[DONE]" or chunk["model"] == "echo-model-name" for chunk in chunks
    )
    assert context.calls == [
        ("enforce", None),
        ("db_usage", {"prompt_tokens": 2, "completion_tokens": 4, "total_tokens": 6}),
        (
            "redis_usage",
            {"prompt_tokens": 2, "completion_tokens": 4, "total_tokens": 6},
        ),
    ]


def test_openai_compat_requires_user_message(
    openai_client: tuple[TestClient, SimpleNamespace],
) -> None:
    client, context = openai_client

    response = client.post(
        f"/api/v1/public/apps/{context.app_id}/openai/v1/chat/completions",
        headers=context.auth_header,
        json={
            "model": "ignored",
            "messages": [{"role": "system", "content": "no user"}],
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "no_user_message"
