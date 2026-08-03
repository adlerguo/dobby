import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


INTENTS = {
    "kb_qa",
    "doc_lookup",
    "task_action",
    "data_query",
    "chit_chat",
    "unsupported",
    "unsafe",
}


@dataclass
class IntentResult:
    intent: str
    confidence: float
    reason: str | None = None
    policy: str | None = None
    source: str = "disabled"
    fallback: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "reason": self.reason,
            "policy": self.policy,
            "source": self.source,
            "fallback": self.fallback,
        }


IntentLLMClassifier = Callable[[str], Awaitable[str]]


async def classify_intent(
    query: str,
    config: dict | None,
    *,
    request_mode: str | None = None,
    skip_intent: bool = False,
    llm_classifier: IntentLLMClassifier | None = None,
) -> IntentResult:
    resolved = resolve_intent_config(config, request_mode=request_mode)
    if skip_intent or not resolved["enabled"]:
        return IntentResult(
            intent="kb_qa",
            confidence=1.0,
            reason="intent_disabled",
            policy="answer",
            source="disabled",
        )

    rule_result = classify_intent_rule(query)
    if rule_result.intent in {"unsafe", "unsupported"}:
        return apply_intent_policy(rule_result, resolved)

    if resolved["mode"] == "llm":
        if llm_classifier is not None:
            try:
                llm_result = parse_intent_json(await llm_classifier(query))
                llm_result.source = "llm"
                return apply_intent_policy(llm_result, resolved)
            except Exception:
                rule_result.fallback = True
                rule_result.source = "fallback"
                rule_result.reason = "llm_intent_failed"
                return apply_intent_policy(rule_result, resolved)
        rule_result.fallback = True
        rule_result.source = "fallback"
        rule_result.reason = "llm_intent_not_configured"
        return apply_intent_policy(rule_result, resolved)

    rule_result.source = "rule"
    return apply_intent_policy(rule_result, resolved)


def resolve_intent_config(
    agent_config: dict | None, *, request_mode: str | None = None
) -> dict[str, Any]:
    config = agent_config or {}
    intent = config.get("intent") if isinstance(config.get("intent"), dict) else {}
    mode = request_mode or intent.get("mode") or "rule"
    if mode not in {"rule", "llm"}:
        mode = "rule"
    return {
        "enabled": bool(intent.get("enabled", False)),
        "mode": mode,
        "low_confidence_threshold": coerce_float(
            intent.get("low_confidence_threshold"), 0.55, 0.0, 1.0
        ),
        "clarify_on_low_confidence": bool(
            intent.get("clarify_on_low_confidence", True)
        ),
        "block_unsafe": bool(intent.get("block_unsafe", True)),
    }


def classify_intent_rule(query: str) -> IntentResult:
    normalized = query.strip().lower()
    if not normalized:
        return IntentResult("kb_qa", 0.4, "empty_query", "clarify", "rule")

    if has_any(normalized, UNSAFE_PATTERNS):
        return IntentResult("unsafe", 0.92, "unsafe_keyword", "block", "rule")
    if has_any(normalized, UNSUPPORTED_PATTERNS):
        return IntentResult("unsupported", 0.82, "unsupported_keyword", "explain", "rule")
    if normalized.endswith(("要注意什么", "是什么", "有哪些", "怎么做")) and not has_any(
        normalized, ("请创建", "帮我创建", "提交", "调用", "执行", "发起", "生成工单")
    ):
        return IntentResult("kb_qa", 0.72, "question_pattern", "answer", "rule")
    if has_any(normalized, TASK_PATTERNS):
        return IntentResult("task_action", 0.78, "task_keyword", "tool_or_answer", "rule")
    if has_any(normalized, DATA_PATTERNS):
        return IntentResult("data_query", 0.74, "data_keyword", "query_or_answer", "rule")
    if has_any(normalized, DOC_PATTERNS):
        return IntentResult("doc_lookup", 0.76, "document_lookup_keyword", "retrieve", "rule")
    if re.fullmatch(r"[\s\S]{0,20}(你好|hi|hello|谢谢|thanks)[\s\S]{0,20}", normalized):
        return IntentResult("chit_chat", 0.72, "chat_keyword", "answer", "rule")
    return IntentResult("kb_qa", 0.68, "default_rule", "answer", "rule")


def parse_intent_json(raw: str) -> IntentResult:
    payload = json.loads(extract_json_object(raw))
    intent = str(payload.get("intent") or "kb_qa")
    if intent not in INTENTS:
        intent = "kb_qa"
    confidence = coerce_float(payload.get("confidence"), 0.5, 0.0, 1.0)
    return IntentResult(
        intent=intent,
        confidence=confidence,
        reason=str(payload.get("reason") or "") or None,
        policy=str(payload.get("policy") or payload.get("recommended_policy") or "")
        or None,
        source="llm",
    )


def apply_intent_policy(result: IntentResult, config: dict[str, Any]) -> IntentResult:
    if result.intent == "unsafe" and config["block_unsafe"]:
        result.policy = "block"
        return result
    if result.intent == "unsupported":
        result.policy = result.policy or "explain"
        return result
    if (
        result.confidence < config["low_confidence_threshold"]
        and config["clarify_on_low_confidence"]
    ):
        result.policy = "clarify"
    return result


def extract_json_object(raw: str) -> str:
    raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("intent_json_not_found")
    return raw[start : end + 1]


def has_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


def coerce_float(value: object, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, minimum), maximum)


UNSAFE_PATTERNS = (
    "越权",
    "盗取",
    "破解",
    "绕过权限",
    "泄露密码",
    "删除所有",
    "drop table",
    "ignore previous",
)
UNSUPPORTED_PATTERNS = (
    "预测彩票",
    "算命",
    "医疗诊断",
    "法律判决",
    "代写违法",
)
TASK_PATTERNS = ("发送", "创建", "审批", "提交", "调用", "执行", "发起", "生成工单")
DATA_PATTERNS = ("统计", "报表", "sql", "查询数据", "销量", "收入", "同比", "环比")
DOC_PATTERNS = ("出处", "来源", "第几页", "文档", "资料", "原文", "引用")
