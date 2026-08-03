import asyncio

from app.orchestrator.context import estimate_tokens
from app.orchestrator.context_compression import compress_history_if_needed
from app.schemas import ContextMessageOut


def run(awaitable):
    return asyncio.run(awaitable)


def message(role: str, content: str) -> ContextMessageOut:
    return ContextMessageOut(role=role, content=content, tokens=estimate_tokens(content))


def test_recent_only_keeps_compatible_recent_messages() -> None:
    history = [message("user", f"问题 {index}") for index in range(5)]

    result = run(
        compress_history_if_needed(
            history,
            {
                "context_compression": {
                    "enabled": True,
                    "strategy": "recent_only",
                    "trigger_tokens": 1,
                    "keep_recent": 2,
                }
            },
            token_estimator=estimate_tokens,
        )
    )

    assert [item.content for item in result.messages] == ["问题 3", "问题 4"]
    assert result.compressed_message_count == 3


def test_hybrid_generates_summary_and_keeps_recent_messages() -> None:
    history = [message("user", "合同审批需要法务确认和预算编号") for _ in range(8)]

    result = run(
        compress_history_if_needed(
            history,
            {
                "context_compression": {
                    "enabled": True,
                    "strategy": "hybrid",
                    "trigger_tokens": 1,
                    "keep_recent": 2,
                }
            },
            token_estimator=estimate_tokens,
        )
    )

    assert result.summary
    assert result.messages[0].role == "system"
    assert len(result.messages) == 3
    assert result.compressed_tokens < result.original_tokens


def test_summary_failure_falls_back_recent_only() -> None:
    async def broken_summary(messages, max_tokens):
        raise RuntimeError("summary_failed")

    history = [message("user", f"历史 {index}") for index in range(6)]
    result = run(
        compress_history_if_needed(
            history,
            {
                "context_compression": {
                    "enabled": True,
                    "strategy": "summary",
                    "trigger_tokens": 1,
                    "keep_recent": 2,
                }
            },
            token_estimator=estimate_tokens,
            summary_builder=broken_summary,
        )
    )

    assert result.fallback is True
    assert result.strategy == "recent_only"
    assert len(result.messages) == 2


def test_empty_history_is_safe() -> None:
    result = run(
        compress_history_if_needed(
            [],
            {"context_compression": {"enabled": True}},
            token_estimator=estimate_tokens,
        )
    )

    assert result.messages == []
    assert result.original_tokens == 0
