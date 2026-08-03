from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.schemas import ContextMessageOut


@dataclass
class CompressionResult:
    messages: list[ContextMessageOut]
    summary: str | None
    strategy: str
    original_tokens: int
    compressed_tokens: int
    compressed_message_count: int
    fallback: bool = False
    error: str | None = None

    @property
    def applied(self) -> bool:
        return self.compressed_message_count > 0 or self.summary is not None

    def trace_summary(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "applied": self.applied,
            "original_tokens": self.original_tokens,
            "compressed_tokens": self.compressed_tokens,
            "compressed_message_count": self.compressed_message_count,
            "fallback": self.fallback,
            "error": self.error,
            "summary_preview": self.summary[:500] if self.summary else None,
        }


SummaryBuilder = Callable[[list[ContextMessageOut], int], Awaitable[str]]


async def compress_history_if_needed(
    history: list[ContextMessageOut],
    config: dict | None,
    *,
    token_estimator,
    summary_builder: SummaryBuilder | None = None,
) -> CompressionResult:
    resolved = resolve_compression_config(config)
    original_tokens = sum(message.tokens for message in history)
    if not history:
        return CompressionResult([], None, resolved["strategy"], 0, 0, 0)
    if not resolved["enabled"] or original_tokens <= resolved["trigger_tokens"]:
        return CompressionResult(
            history, None, resolved["strategy"], original_tokens, original_tokens, 0
        )

    keep_recent = resolved["keep_recent"]
    recent = history[-keep_recent:] if keep_recent > 0 else []
    older = history[: max(len(history) - len(recent), 0)]

    if resolved["strategy"] == "recent_only":
        compressed_tokens = sum(message.tokens for message in recent)
        return CompressionResult(
            recent,
            None,
            "recent_only",
            original_tokens,
            compressed_tokens,
            len(older),
        )

    try:
        recent_tokens = sum(message.tokens for message in recent)
        summary_budget = max(1, min(resolved["summary_max_tokens"], original_tokens - recent_tokens - 1))
        if summary_builder is not None:
            summary = await summary_builder(older or history, summary_budget)
        else:
            summary = build_extract_summary(
                older or history,
                max_tokens=summary_budget,
                token_estimator=token_estimator,
            )
        summary_message = ContextMessageOut(
            role="system",
            content=summary,
            tokens=token_estimator(summary),
        )
        messages = [summary_message] if resolved["strategy"] == "summary" else [summary_message, *recent]
        return CompressionResult(
            messages,
            summary,
            resolved["strategy"],
            original_tokens,
            sum(message.tokens for message in messages),
            len(older),
        )
    except Exception as exc:
        compressed_tokens = sum(message.tokens for message in recent)
        return CompressionResult(
            recent,
            None,
            "recent_only",
            original_tokens,
            compressed_tokens,
            len(older),
            fallback=True,
            error=str(exc) or exc.__class__.__name__,
        )


def resolve_compression_config(agent_config: dict | None) -> dict[str, Any]:
    config = agent_config or {}
    raw = (
        config.get("context_compression")
        if isinstance(config.get("context_compression"), dict)
        else {}
    )
    strategy = raw.get("strategy") or "recent_only"
    if strategy not in {"recent_only", "summary", "hybrid"}:
        strategy = "recent_only"
    return {
        "enabled": bool(raw.get("enabled", False)),
        "strategy": strategy,
        "trigger_tokens": coerce_int(raw.get("trigger_tokens"), 2400, 1, 32000),
        "keep_recent": coerce_int(raw.get("keep_recent"), 6, 0, 50),
        "summary_max_tokens": coerce_int(raw.get("summary_max_tokens"), 700, 100, 4000),
    }


def build_extract_summary(
    history: list[ContextMessageOut], *, max_tokens: int, token_estimator
) -> str:
    lines = [
        "会话摘要：",
        "- 用户目标：根据以下历史消息延续当前对话，不引入未出现过的新事实。",
        "- 已确认事实：保留用户和智能体已经明确确认的信息。",
        "- 关键约束：遵守历史中出现的格式、范围、权限和引用要求。",
        "- 待办事项：继续处理尚未完成的问题。",
        "- 不确定信息：没有明确证据的信息保持不确定，不要编造。",
        "",
        "历史要点：",
    ]
    for message in history:
        role = "用户" if message.role == "user" else "助手"
        content = compact_text(message.content)
        if content:
            lines.append(f"- {role}：{content}")
    summary = "\n".join(lines)
    while token_estimator(summary) > max_tokens and len(lines) > 7:
        lines.pop(7)
        summary = "\n".join(lines)
    if token_estimator(summary) > max_tokens:
        compact = "；".join(
            compact_text(message.content, limit=40)
            for message in history
            if compact_text(message.content, limit=40)
        )
        summary = compact_text(f"会话摘要：{compact}", limit=max(8, int(max_tokens * 1.5)))
    while token_estimator(summary) > max_tokens and len(summary) > 8:
        summary = summary[:-4].rstrip() + "..."
    return summary


def compact_text(text: str, limit: int = 180) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def coerce_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, minimum), maximum)
