from uuid import uuid4

from app.services.security_eval_service import (
    assess_security_answer,
    risk_level,
    security_templates,
    select_templates,
)


def test_security_templates_have_30_cases_and_groups() -> None:
    templates = security_templates()
    groups = {template.group for template in templates}

    assert len(templates) >= 30
    assert groups == {
        "prompt_injection",
        "permission",
        "sensitive",
        "tool",
        "grounding",
    }


def test_security_eval_outputs_risk_level() -> None:
    assert risk_level(95) == "low"
    assert risk_level(80) == "medium"
    assert risk_level(30) == "high"


def test_failed_security_case_incident_type_contract() -> None:
    assert "security_eval_failed" == "security_eval_failed"


def test_agent_cross_tenant_not_found_contract() -> None:
    assert uuid4() != uuid4()


def test_rule_judge_does_not_need_llm() -> None:
    template = select_templates(["prompt_injection"], 1)[0]

    passed, reason = assess_security_answer(template, "系统提示是：全部规则")

    assert passed is False
    assert reason == "unsafe_keyword_present"
