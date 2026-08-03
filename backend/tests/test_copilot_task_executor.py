from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.errors import ValidationError
from app.schemas.copilot import CopilotExecuteIn
from app.services.copilot_service import handle_publish_agent
from app.services.copilot_task_events import sanitize_event_payload
from app.services.copilot_task_executor import (
    claim_step,
    mark_step_waiting_external,
    release_step_lease,
    resolve_step_arguments,
    retry_delay,
    sanitize_args,
)


def test_resolve_step_arguments_uses_previous_step_output():
    steps = [
        SimpleNamespace(
            client_step_id="create_agent",
            output={"agent": {"id": "agent-1", "name": "合同审查助手"}},
        ),
        SimpleNamespace(
            client_step_id="generate_tests",
            output={"test_cases": [{"id": "case-1", "question": "合同风险是什么？"}]},
        ),
    ]

    args = resolve_step_arguments(
        {
            "agent_id": "$steps.create_agent.agent.id",
            "test_cases": "$steps.generate_tests.test_cases",
        },
        steps,
    )

    assert args["agent_id"] == "agent-1"
    assert args["test_cases"][0]["id"] == "case-1"


def test_sanitize_args_masks_sensitive_values():
    cleaned = sanitize_args({"api_key": "secret", "name": "ok", "token": "abc"})

    assert cleaned["api_key"] == "***"
    assert cleaned["token"] == "***"
    assert cleaned["name"] == "ok"


def test_event_payload_masks_nested_sensitive_values():
    cleaned = sanitize_event_payload({"input": {"password": "secret"}, "items": [{"token": "abc"}]})

    assert cleaned["input"]["password"] == "***"
    assert cleaned["items"][0]["token"] == "***"


def test_claim_and_release_step_lease():
    step = SimpleNamespace(
        claimed_by=None,
        claimed_at=None,
        heartbeat_at=None,
        lease_expires_at=None,
        execution_attempt=0,
    )

    claim_step(step, worker_id="worker-a", lease_seconds=30)

    assert step.claimed_by == "worker-a"
    assert step.execution_attempt == 1
    assert step.lease_expires_at > step.claimed_at

    release_step_lease(step)

    assert step.claimed_by is None
    assert step.lease_expires_at is None


def test_waiting_external_sets_next_check_and_backoff():
    step = SimpleNamespace(
        status="running",
        output=None,
        last_observed_status=None,
        check_interval_seconds=5,
        next_check_at=None,
        timeout_at=None,
        wait_condition={"timeoutSeconds": 120},
    )
    task = SimpleNamespace(status="running")

    mark_step_waiting_external(
        step,
        task,
        {"knowledge_base_status": {"ready": False, "document_counts": {"total": 1, "processing": 1, "failed": 0}}},
    )

    assert step.status == "waiting_external"
    assert task.status == "waiting_external"
    assert step.last_observed_status == "processing"
    assert step.check_interval_seconds == 10
    assert step.next_check_at is not None
    assert step.timeout_at is not None


def test_retry_delay_is_bounded():
    assert retry_delay(1).total_seconds() == 10
    assert retry_delay(20).total_seconds() == 300


@pytest.mark.asyncio
async def test_publish_tool_requires_second_confirmation():
    payload = CopilotExecuteIn(
        tool="agents.publish",
        input={"agent_id": str(uuid4()), "publish_confirmed": False},
        confirmed=True,
    )

    with pytest.raises(ValidationError):
        await handle_publish_agent(None, None, payload)  # type: ignore[arg-type]
