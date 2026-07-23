"""
Optional compose-level smoke tests for the agent execution stack.

These tests require a running docker compose stack and valid smoke IDs/tokens.
They are skipped unless RUN_AGENT_STACK_SMOKE=1 is present in the environment.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pytest


pytestmark = pytest.mark.integration


def smoke_enabled() -> bool:
    return os.getenv("RUN_AGENT_STACK_SMOKE") == "1"


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is required for agent stack smoke tests")
    return value


def backend_url(path: str) -> str:
    base_url = os.getenv(
        "SMOKE_BACKEND_BASE_URL", "http://localhost:8000/api/v1"
    ).rstrip("/")
    return f"{base_url}{path}"


def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {require_env('SMOKE_AUTH_TOKEN')}"}


def tool_call_payload(
    tool_id: str, input_payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "query": "agent stack smoke test",
        "tool_calls": [
            {"tool_id": tool_id, "input": input_payload or {"payload": "smoke"}}
        ],
    }


@pytest.fixture(autouse=True)
def skip_unless_enabled() -> None:
    if not smoke_enabled():
        pytest.skip(
            "set RUN_AGENT_STACK_SMOKE=1 to run compose integration smoke tests"
        )


def test_bound_tool_agent_non_stream_returns_200() -> None:
    agent_id = require_env("SMOKE_AGENT_ID")
    tool_id = require_env("SMOKE_TOOL_ID")

    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            backend_url(f"/agents/{agent_id}/run"),
            headers=auth_headers(),
            json=tool_call_payload(tool_id),
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tool_results"]
    assert body["tool_results"][0]["status"] in {"ok", "failed"}


def test_bound_tool_agent_stream_receives_done() -> None:
    agent_id = require_env("SMOKE_AGENT_ID")
    tool_id = require_env("SMOKE_TOOL_ID")
    payload = {"agent_id": agent_id, **tool_call_payload(tool_id)}
    events: list[str] = []

    with httpx.Client(timeout=60.0) as client:
        with client.stream(
            "POST", backend_url("/chat"), headers=auth_headers(), json=payload
        ) as response:
            assert response.status_code == 200, response.text
            for line in response.iter_lines():
                if line.startswith("event: "):
                    events.append(line.removeprefix("event: ").strip())
                if events and events[-1] == "done":
                    break

    assert "done" in events


def test_failing_tool_run_persists_failed_trace_when_db_url_is_configured() -> None:
    psycopg = pytest.importorskip("psycopg")
    agent_id = require_env("SMOKE_AGENT_ID")
    failing_tool_id = require_env("SMOKE_FAILING_TOOL_ID")
    database_url = require_env("SMOKE_DATABASE_URL")

    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            backend_url(f"/agents/{agent_id}/run"),
            headers=auth_headers(),
            json=tool_call_payload(failing_tool_id),
        )
    assert response.status_code == 200, response.text
    conversation_id = response.json()["conversation_id"]

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "select status from run_traces where conversation_id = %s and span_type = 'agent' order by created_at desc limit 1",
                (conversation_id,),
            )
            row = cursor.fetchone()

    assert row is not None
    assert row[0] == "failed"


def test_direct_code_tool_is_forbidden_when_configured() -> None:
    code_tool_id = os.getenv("SMOKE_CODE_TOOL_ID")
    if not code_tool_id:
        pytest.skip("SMOKE_CODE_TOOL_ID not configured")

    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            backend_url(f"/tools/{code_tool_id}/run"),
            headers=auth_headers(),
            json={"input": {"code": "print('should be blocked')"}},
        )

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["error"] == "forbidden"


def test_http_tool_blocks_internal_maas_when_configured() -> None:
    http_tool_id = os.getenv("SMOKE_HTTP_TOOL_ID")
    if not http_tool_id:
        pytest.skip("SMOKE_HTTP_TOOL_ID not configured")

    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            backend_url(f"/tools/{http_tool_id}/run"),
            headers=auth_headers(),
            json={"input": {"url": "http://maas:8100/health"}},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "failed"
    assert body["output"]["error"] == "ssrf_blocked"


def test_maas_admin_rejects_missing_service_token_when_configured() -> None:
    maas_base_url = os.getenv("SMOKE_MAAS_BASE_URL")
    if not maas_base_url:
        pytest.skip("SMOKE_MAAS_BASE_URL not configured")

    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{maas_base_url.rstrip('/')}/admin/channels")

    assert response.status_code == 401
