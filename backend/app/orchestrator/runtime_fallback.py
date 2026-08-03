from dataclasses import dataclass
from typing import Any


FALLBACK_REASONS = {
    "model_error",
    "retrieval_empty",
    "tool_error",
    "timeout",
    "policy_blocked",
    "unsupported_intent",
    "low_confidence",
    "rerank_fallback",
    "unknown",
}


@dataclass(frozen=True)
class FallbackResult:
    applied: bool
    reason: str | None = None
    message: str | None = None
    detail: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "fallback_applied": self.applied,
            "fallback_reason": self.reason,
            "fallback_message": self.message,
            "fallback_detail": self.detail or {},
        }


def fallback_config(agent_config: dict | None) -> dict[str, Any]:
    config = agent_config or {}
    raw = config.get("fallback") if isinstance(config.get("fallback"), dict) else {}
    return {
        "enabled": raw.get("enabled", True) is not False,
        "citation_required": bool(raw.get("citation_required", False)),
        "no_citation_message": raw.get("no_citation_message")
        or "我没有在已绑定知识库中找到足够依据，暂不能给出确定答案。",
        "tool_error_message": raw.get("tool_error_message")
        or "工具调用失败，请稍后重试或联系管理员。",
        "model_error_message": raw.get("model_error_message")
        or "模型服务暂时不可用，请稍后重试。",
        "unsupported_message": raw.get("unsupported_message")
        or "这个问题超出当前智能体的能力范围。",
        "unsafe_message": raw.get("unsafe_message") or "该请求存在安全风险，无法处理。",
        "low_confidence_message": raw.get("low_confidence_message")
        or "我还不确定你的具体意图，请补充目标、范围或期望输出。",
    }


def no_fallback() -> FallbackResult:
    return FallbackResult(False)


def make_fallback(
    reason: str,
    config: dict[str, Any],
    *,
    detail: dict[str, Any] | None = None,
) -> FallbackResult:
    if not config.get("enabled", True) and reason not in {
        "policy_blocked",
        "unsupported_intent",
        "low_confidence",
    }:
        return no_fallback()
    message_key = {
        "model_error": "model_error_message",
        "retrieval_empty": "no_citation_message",
        "tool_error": "tool_error_message",
        "policy_blocked": "unsafe_message",
        "unsupported_intent": "unsupported_message",
        "low_confidence": "low_confidence_message",
        "timeout": "model_error_message",
    }.get(reason, "model_error_message")
    return FallbackResult(
        applied=True,
        reason=reason if reason in FALLBACK_REASONS else "unknown",
        message=str(config.get(message_key) or ""),
        detail=detail or {},
    )


def fallback_for_intent(intent_result, config: dict[str, Any]) -> FallbackResult:
    if getattr(intent_result, "intent", None) == "unsafe" and getattr(
        intent_result, "policy", None
    ) == "block":
        return make_fallback(
            "policy_blocked",
            config,
            detail=getattr(intent_result, "as_dict", lambda: {})(),
        )
    if getattr(intent_result, "intent", None) == "unsupported":
        return make_fallback(
            "unsupported_intent",
            config,
            detail=getattr(intent_result, "as_dict", lambda: {})(),
        )
    if getattr(intent_result, "policy", None) == "clarify":
        return make_fallback(
            "low_confidence",
            config,
            detail=getattr(intent_result, "as_dict", lambda: {})(),
        )
    return no_fallback()


def fallback_for_citations(citation_count: int, config: dict[str, Any]) -> FallbackResult:
    if config.get("citation_required") and citation_count <= 0:
        return make_fallback("retrieval_empty", config)
    return no_fallback()


def fallback_for_tool_failure(tool_results: list[Any], config: dict[str, Any]) -> FallbackResult:
    failed = [result for result in tool_results if getattr(result, "status", None) == "failed"]
    if not failed:
        return no_fallback()
    return make_fallback(
        "tool_error",
        config,
        detail={"failed_tools": [getattr(result, "tool_name", "") for result in failed]},
    )
