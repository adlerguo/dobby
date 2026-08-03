from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.errors import ValidationError
from app.schemas.copilot_task import CopilotTaskPlan, CopilotTaskPlanStep
from app.services.copilot_planner import validate_plan


def fake_auth(permissions=None, roles=None):
    return SimpleNamespace(
        roles=roles or [],
        permissions=permissions or ["agent:publish", "kb:create"],
        tenant_id=uuid4(),
        user_id=uuid4(),
    )


def test_task_plan_schema_accepts_structured_steps():
    plan = CopilotTaskPlan(
        title="合同助手计划",
        goal="创建合同助手并测试",
        steps=[
            CopilotTaskPlanStep(
                clientStepId="create_agent",
                order=1,
                title="创建草稿",
                toolName="agents.create_draft",
                toolArguments={"name": "合同审查助手"},
                riskLevel="L2",
                requiresConfirmation=True,
            )
        ],
    )

    assert plan.steps[0].toolName == "agents.create_draft"


def test_task_plan_schema_accepts_empty_informational_plan():
    plan = CopilotTaskPlan(
        title="失败任务恢复计划",
        goal="继续上次失败任务",
        summary="没有可安全自动恢复的步骤。",
        steps=[],
        warnings=["请人工检查失败原因。"],
    )

    validate_plan(plan, fake_auth())
    assert plan.steps == []


def test_unregistered_tool_is_rejected():
    plan = CopilotTaskPlan(
        title="非法计划",
        goal="运行外部代码",
        steps=[
            CopilotTaskPlanStep(
                clientStepId="run_shell",
                order=1,
                title="运行命令",
                toolName="shell.run",
            )
        ],
    )

    with pytest.raises(ValidationError):
        validate_plan(plan, fake_auth())


def test_l3_step_requires_confirmation():
    plan = CopilotTaskPlan(
        title="发布计划",
        goal="发布智能体",
        steps=[
            CopilotTaskPlanStep(
                clientStepId="publish",
                order=1,
                title="发布",
                toolName="agents.publish",
                toolArguments={"agent_id": str(uuid4())},
                riskLevel="L3",
                requiresConfirmation=False,
            )
        ],
    )

    with pytest.raises(ValidationError):
        validate_plan(plan, fake_auth())


def test_dependency_cycle_is_rejected():
    plan = CopilotTaskPlan(
        title="循环计划",
        goal="循环依赖",
        steps=[
            CopilotTaskPlanStep(clientStepId="a", order=1, title="A", toolName="agents.generate_test_cases", dependencies=["b"]),
            CopilotTaskPlanStep(clientStepId="b", order=2, title="B", toolName="agents.generate_test_cases", dependencies=["a"]),
        ],
    )

    with pytest.raises(ValidationError):
        validate_plan(plan, fake_auth())
