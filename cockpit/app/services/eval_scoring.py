from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScoreResult:
    score: float
    passed: bool
    reason: str | None = None


def assess_eval_case(
    answer: str,
    expected_answer: str | None = None,
    expected_keywords: list[str] | None = None,
    scoring_config: dict | None = None,
    latency_ms: int | None = None,
) -> ScoreResult:
    # 移植 legacy assess_eval_case 的规则评分思路；LLM-as-judge 仅保留占位。
    config = scoring_config or {}
    expected_keywords = expected_keywords or []
    assert_type = config.get("assert_type")
    if not assert_type:
        assert_type = "keyword_all" if expected_keywords else "contains"

    if config.get("judge_config"):
        raise NotImplementedError("llm_judge_not_implemented")

    if assert_type == "always_pass":
        return ScoreResult(score=1.0, passed=True)

    if assert_type == "exact":
        passed = answer.strip() == (expected_answer or "").strip()
        return ScoreResult(score=1.0 if passed else 0.0, passed=passed, reason=None if passed else "答案未精确匹配")

    if assert_type == "contains":
        needle = expected_answer or ""
        passed = bool(needle) and needle in answer
        return ScoreResult(score=1.0 if passed else 0.0, passed=passed, reason=None if passed else "答案未包含期望文本")

    if assert_type == "not_contains":
        needle = expected_answer or ""
        passed = bool(needle) and needle not in answer
        return ScoreResult(score=1.0 if passed else 0.0, passed=passed, reason=None if passed else "答案包含禁止文本")

    if assert_type in {"keyword_all", "keyword_any"}:
        hits = [keyword for keyword in expected_keywords if keyword and keyword in answer]
        if assert_type == "keyword_all":
            passed = len(hits) == len(expected_keywords) and bool(expected_keywords)
            score = len(hits) / len(expected_keywords) if expected_keywords else 0.0
            reason = None if passed else f"关键词命中不足：{len(hits)}/{len(expected_keywords)}"
            return ScoreResult(score=score, passed=passed, reason=reason)
        passed = bool(hits)
        score = 1.0 if passed else 0.0
        return ScoreResult(score=score, passed=passed, reason=None if passed else "未命中任一关键词")

    if assert_type == "length":
        min_length = config.get("min_length")
        max_length = config.get("max_length")
        passed = True
        reasons = []
        if min_length is not None and len(answer) < int(min_length):
            passed = False
            reasons.append("答案长度低于下限")
        if max_length is not None and len(answer) > int(max_length):
            passed = False
            reasons.append("答案长度超过上限")
        return ScoreResult(score=1.0 if passed else 0.0, passed=passed, reason="；".join(reasons) or None)

    if assert_type == "latency_ms":
        threshold = config.get("threshold_ms")
        passed = latency_ms is not None and threshold is not None and latency_ms <= int(threshold)
        return ScoreResult(score=1.0 if passed else 0.0, passed=passed, reason=None if passed else "响应耗时超过阈值")

    return ScoreResult(score=0.0, passed=False, reason=f"未知评分规则：{assert_type}")
