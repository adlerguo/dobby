import asyncio
from types import SimpleNamespace
from uuid import uuid4

from pydantic import TypeAdapter

from app.orchestrator.context import ids_from_snapshot
from app.orchestrator.runtime import agent_from_runtime_snapshot
from app.schemas.agent_run import AgentRunIn
from app.schemas.publish import (
    PublishedAppRollbackIn,
    PublishedAppVersionCreate,
    PublishPrecheckOut,
)
from app.services.publish_service import check, is_model_ready
import app.services.publish_service as publish_service


def run_async(awaitable):
    return asyncio.run(awaitable)


def test_runtime_snapshot_overrides_agent_config_without_mutating_live_agent() -> None:
    model_id = uuid4()
    live_agent = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        status="active",
        name="live",
        type="assistant",
        persona="live persona",
        config={"temperature": 0.1},
        model_id=uuid4(),
    )
    snapshot = {
        "agent": {
            "name": "published",
            "type": "nl2data",
            "persona": "published persona",
            "config": {"temperature": 0.7},
            "model_id": str(model_id),
        }
    }

    runtime_agent = agent_from_runtime_snapshot(live_agent, snapshot)

    assert runtime_agent.id == live_agent.id
    assert runtime_agent.name == "published"
    assert runtime_agent.type == "nl2data"
    assert runtime_agent.persona == "published persona"
    assert runtime_agent.config == {"temperature": 0.7}
    assert runtime_agent.model_id == model_id
    assert live_agent.name == "live"
    assert live_agent.config == {"temperature": 0.1}


def test_snapshot_resource_ids_ignore_invalid_values() -> None:
    kb_id = uuid4()
    tool_id = uuid4()
    snapshot = {
        "kb_ids": [str(kb_id), "bad-id", None],
        "tool_ids": [str(tool_id)],
    }

    assert ids_from_snapshot(snapshot, "kb_ids") == [kb_id]
    assert ids_from_snapshot(snapshot, "tool_ids") == [tool_id]
    assert ids_from_snapshot(snapshot, "missing") == []


def test_publish_precheck_contract_supports_warning_and_blocked_states() -> None:
    result = PublishPrecheckOut(
        status="warning",
        checks=[
            check("agent_active", "passed", "block", "智能体已启用"),
            check("security_eval", "warning", "warning", "open 安全评测失败 1 个"),
        ],
    )

    assert result.status == "warning"
    assert result.checks[0]["level"] == "block"
    assert result.checks[1]["status"] == "warning"


def test_publish_precheck_model_ready_uses_is_active_flag() -> None:
    assert is_model_ready(SimpleNamespace(is_active=True)) is True
    assert is_model_ready(SimpleNamespace(is_active=None)) is True
    assert is_model_ready(SimpleNamespace(is_active=False)) is False
    assert is_model_ready(None) is False


def test_publish_version_and_rollback_payloads_are_strict() -> None:
    create_payload = PublishedAppVersionCreate(
        title="正式版", release_note="更新知识库", activate=True, force=False
    )
    rollback_payload = PublishedAppRollbackIn(version_id=uuid4())

    assert create_payload.activate is True
    assert rollback_payload.version_id is not None


def test_public_agent_payload_accepts_internal_runtime_snapshot() -> None:
    adapter = TypeAdapter(AgentRunIn)
    payload = adapter.validate_python(
        {
            "query": "hello",
            "runtime_snapshot": {
                "schema_version": "m5_v1",
                "agent": {"config": {"temperature": 0.2}},
                "kb_ids": [],
                "tool_ids": [],
            },
        }
    )

    assert payload.runtime_snapshot is not None
    assert payload.runtime_snapshot["schema_version"] == "m5_v1"


def test_publish_confirmation_hash_changes_when_config_changes(monkeypatch) -> None:
    class FakeAgentRepository:
        def __init__(self, db, tenant_id) -> None:
            pass

        async def get_kb_ids(self, agent_id):
            return []

        async def get_tool_ids(self, agent_id):
            return []

    class FakeDb:
        async def get(self, model, model_id):
            return SimpleNamespace(id=model_id, name="model")

    monkeypatch.setattr(publish_service, "AgentRepository", FakeAgentRepository)
    tenant_id = uuid4()
    agent = SimpleNamespace(
        id=uuid4(),
        name="agent",
        type="assistant",
        persona="v1",
        config={"temperature": 0.2},
        model_id=uuid4(),
        updated_at=None,
    )

    first = run_async(
        publish_service.agent_configuration_hash(FakeDb(), tenant_id=tenant_id, agent=agent)
    )
    agent.persona = "v2"
    second = run_async(
        publish_service.agent_configuration_hash(FakeDb(), tenant_id=tenant_id, agent=agent)
    )

    assert first != second


def test_publish_confirmation_rejects_stale_hash(monkeypatch) -> None:
    class FakeAgentRepository:
        def __init__(self, db, tenant_id) -> None:
            pass

        async def get_kb_ids(self, agent_id):
            return []

        async def get_tool_ids(self, agent_id):
            return []

    class FakeDb:
        async def get(self, model, model_id):
            return SimpleNamespace(id=model_id, name="model")

    monkeypatch.setattr(publish_service, "AgentRepository", FakeAgentRepository)
    tenant_id = uuid4()
    agent = SimpleNamespace(
        id=uuid4(),
        name="agent",
        type="assistant",
        persona="v1",
        config={"temperature": 0.2},
        model_id=uuid4(),
        updated_at=None,
    )
    valid_hash = run_async(
        publish_service.agent_configuration_hash(FakeDb(), tenant_id=tenant_id, agent=agent)
    )

    run_async(
        publish_service.validate_publish_confirmation(
            FakeDb(),
            tenant_id=tenant_id,
            agent=agent,
            expected_configuration_hash=valid_hash,
        )
    )

    agent.config = {"temperature": 0.7}
    try:
        run_async(
            publish_service.validate_publish_confirmation(
                FakeDb(),
                tenant_id=tenant_id,
                agent=agent,
                expected_configuration_hash=valid_hash,
            )
        )
    except ValueError as exc:
        assert str(exc) == "publish_confirmation_stale"
    else:
        raise AssertionError("stale confirmation should be rejected")
