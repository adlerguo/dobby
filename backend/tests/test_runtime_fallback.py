from uuid import uuid4

from app.orchestrator.intent import IntentResult
from app.orchestrator.runtime_fallback import (
    fallback_config,
    fallback_for_citations,
    fallback_for_intent,
    fallback_for_tool_failure,
    make_fallback,
)
from app.schemas import AgentRunOut, ContextBuildOut


def test_citation_required_without_citation_returns_no_citation_fallback() -> None:
    fallback = fallback_for_citations(
        0, fallback_config({"fallback": {"citation_required": True}})
    )

    assert fallback.applied is True
    assert fallback.reason == "retrieval_empty"


def test_model_error_returns_configured_fallback_message() -> None:
    fallback = make_fallback(
        "model_error",
        fallback_config({"fallback": {"model_error_message": "模型不可用"}}),
    )

    assert fallback.applied is True
    assert fallback.message == "模型不可用"


def test_tool_error_marks_fallback() -> None:
    class ToolResult:
        status = "failed"
        tool_name = "crm"

    fallback = fallback_for_tool_failure([ToolResult()], fallback_config({}))

    assert fallback.applied is True
    assert fallback.reason == "tool_error"
    assert fallback.detail["failed_tools"] == ["crm"]


def test_unsupported_and_unsafe_intent_return_fallbacks() -> None:
    config = fallback_config({})

    unsupported = fallback_for_intent(
        IntentResult("unsupported", 0.8, policy="explain"), config
    )
    unsafe = fallback_for_intent(IntentResult("unsafe", 0.9, policy="block"), config)

    assert unsupported.reason == "unsupported_intent"
    assert unsafe.reason == "policy_blocked"


def test_agent_run_out_contains_fallback_fields() -> None:
    run = AgentRunOut(
        conversation_id=uuid4(),
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        trace_id=uuid4(),
        answer="fallback",
        citations=[],
        tool_results=[],
        usage={},
        context=ContextBuildOut(
            agent_id=uuid4(),
            conversation_id=uuid4(),
            workspace_id=None,
            messages=[],
            tools=[],
            retrieved_chunks=[],
            citations=[],
            token_budget={},
            truncation={},
        ),
        fallback_applied=True,
        fallback_reason="model_error",
        fallback_message="模型不可用",
    )

    assert run.fallback_applied is True
    assert run.fallback_reason == "model_error"
