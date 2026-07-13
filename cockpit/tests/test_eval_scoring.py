import pytest

from app.services.eval_scoring import assess_eval_case


def test_keyword_all_scoring_passes_when_all_keywords_hit():
    result = assess_eval_case(
        answer="答案包含 alpha 和 beta",
        expected_keywords=["alpha", "beta"],
        scoring_config={"assert_type": "keyword_all"},
    )

    assert result.passed is True
    assert result.score == 1.0


def test_keyword_all_scoring_fails_with_readable_reason():
    result = assess_eval_case(
        answer="答案只包含 alpha",
        expected_keywords=["alpha", "beta"],
        scoring_config={"assert_type": "keyword_all"},
    )

    assert result.passed is False
    assert "关键词命中不足" in result.reason


def test_llm_judge_is_placeholder():
    with pytest.raises(NotImplementedError):
        assess_eval_case(answer="x", scoring_config={"judge_config": {"model": "todo"}})
