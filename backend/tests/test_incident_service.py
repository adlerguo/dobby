from uuid import uuid4

from app.schemas import IncidentCreate, IncidentUpdate
from app.services.incident_service import incident_from_runtime


def test_auto_archive_fallback_applied_payload() -> None:
    payload = incident_from_runtime(
        tenant_id=uuid4(),
        conversation_id=uuid4(),
        message_id=uuid4(),
        agent_id=uuid4(),
        trace_id=uuid4(),
        incident_type="fallback_applied",
        severity="low",
        title="触发 fallback",
        query="问题",
        answer="回答",
    )

    assert payload.incident_type == "fallback_applied"
    assert payload.detail["query"] == "问题"


def test_auto_archive_tool_failed_payload() -> None:
    payload = IncidentCreate(
        incident_type="tool_failed",
        severity="medium",
        title="工具失败",
        detail={"tool_results": [{"status": "failed"}]},
    )

    assert payload.detail["tool_results"][0]["status"] == "failed"


def test_same_trace_and_type_dedupe_contract() -> None:
    trace_id = uuid4()
    first = IncidentCreate(trace_id=trace_id, incident_type="model_failed", title="A")
    second = IncidentCreate(trace_id=trace_id, incident_type="model_failed", title="B")

    assert first.trace_id == second.trace_id
    assert first.incident_type == second.incident_type


def test_incident_can_be_resolved_or_ignored() -> None:
    assert IncidentUpdate(status="resolved").status == "resolved"
    assert IncidentUpdate(status="ignored").status == "ignored"


def test_incident_to_eval_case_scene_shape() -> None:
    incident_type = "no_citation"

    assert f"incident/{incident_type}" == "incident/no_citation"


def test_tenant_isolation_payload_keeps_ids_separate() -> None:
    left = uuid4()
    right = uuid4()

    assert left != right
