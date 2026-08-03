from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.errors import ValidationError
from app.models import Agent, CopilotTask, CopilotTaskStep, KnowledgeBase, Model
from app.services.copilot_task_executor import resolve_step_arguments
from app.schemas.copilot_task import CopilotTaskPlan, CopilotTaskPlanStep
from app.services.copilot_service import COPILOT_TOOL_REGISTRY, ensure_tool_permission


async def plan_copilot_task(
    db: AsyncSession,
    *,
    auth: AuthContext,
    goal: str,
    workspace_id: UUID | None = None,
    conversation_id: str | None = None,
) -> CopilotTaskPlan:
    text = goal.strip()
    if not text:
        raise ValidationError(code="copilot_empty_goal", message="目标不能为空")

    if "继续" in text and "失败" in text:
        return await build_failed_task_recovery_plan(db, auth=auth, goal=text, workspace_id=workspace_id)

    if "发布" in text and ("测试" in text or "没问题" in text):
        plan = await build_test_then_publish_plan(db, auth=auth, goal=text)
    elif "发布" in text or "可以发布" in text:
        plan = await build_preflight_plan(db, auth=auth, goal=text)
    elif "知识库" in text and "创建" in text and ("等" in text or "解析" in text or "绑定" in text):
        plan = await build_kb_then_agent_plan(db, auth=auth, goal=text)
    elif "创建" in text and ("智能体" in text or "助手" in text):
        plan = await build_agent_build_plan(db, auth=auth, goal=text)
    else:
        plan = await build_agent_build_plan(db, auth=auth, goal=text)

    validate_plan(plan, auth)
    return plan


async def build_agent_build_plan(db: AsyncSession, *, auth: AuthContext, goal: str) -> CopilotTaskPlan:
    kb = await find_kb(db, auth=auth, goal=goal)
    model = await find_model(db, goal=goal)
    agent_name = infer_agent_name(goal)
    kb_ids = [str(kb.id)] if kb else []
    steps = [
        CopilotTaskPlanStep(
            clientStepId="create_agent",
            order=1,
            title=f"创建{agent_name}草稿",
            description="创建草稿，不自动发布。",
            toolName="agents.create_draft",
            toolArguments={
                "name": agent_name,
                "type": "qa",
                "persona": build_persona(agent_name),
                "model_id": str(model.id) if model else None,
                "kb_ids": kb_ids,
                "tool_ids": [],
                "config": {"temperature": 0.2, "answer_style_enabled": True},
            },
            riskLevel="L2",
            requiresConfirmation=True,
        ),
        CopilotTaskPlanStep(
            clientStepId="generate_tests",
            order=2,
            title="生成 5 个测试问题",
            description="生成结构化测试用例，不证明答案完全正确。",
            toolName="agents.generate_test_cases",
            toolArguments={"agent_id": "$steps.create_agent.agent.id", "count": 5, "topic": agent_name},
            dependencies=["create_agent"],
            riskLevel="L1",
            requiresConfirmation=False,
        ),
        CopilotTaskPlanStep(
            clientStepId="run_tests",
            order=3,
            title="执行测试套件",
            description="执行测试并输出通过、失败和警告。",
            toolName="agents.run_test_suite",
            toolArguments={
                "agent_id": "$steps.create_agent.agent.id",
                "test_cases": "$steps.generate_tests.test_cases",
            },
            dependencies=["generate_tests"],
            riskLevel="L2",
            requiresConfirmation=True,
        ),
    ]
    return CopilotTaskPlan(
        title=f"{agent_name}搭建计划",
        goal=goal,
        summary="创建智能体草稿、绑定已有知识库并执行测试，不自动发布。",
        steps=steps,
        warnings=[] if kb else ["未匹配到明确知识库，草稿将暂不绑定知识库。"],
    )


async def build_failed_task_recovery_plan(
    db: AsyncSession,
    *,
    auth: AuthContext,
    goal: str,
    workspace_id: UUID | None,
) -> CopilotTaskPlan:
    stmt = (
        select(CopilotTask)
        .where(
            CopilotTask.tenant_id == auth.tenant_id,
            CopilotTask.user_id == auth.user_id,
            CopilotTask.status.in_(["failed", "paused", "retrying"]),
        )
        .order_by(CopilotTask.updated_at.desc())
        .limit(10)
    )
    if workspace_id is not None:
        stmt = stmt.where(CopilotTask.workspace_id == workspace_id)
    result = await db.execute(stmt)
    candidates = list(result.scalars().all())
    task = pick_failed_task(candidates, goal)
    if task is None:
        return CopilotTaskPlan(
            title="失败任务恢复计划",
            goal=goal,
            summary="未找到当前账号和工作空间内可恢复的失败任务。",
            steps=[],
            warnings=["没有可安全自动恢复的任务，请先打开任务历史查看失败原因。"],
        )
    step_rows = await db.execute(
        select(CopilotTaskStep).where(CopilotTaskStep.task_id == task.id).order_by(CopilotTaskStep.step_order)
    )
    old_steps = list(step_rows.scalars().all())
    retry_steps: list[CopilotTaskPlanStep] = []
    for step in old_steps:
        if step.status == "succeeded":
            continue
        args = resolve_step_arguments(step.tool_arguments or {}, old_steps)
        if contains_unresolved_reference(args):
            continue
        retry_steps.append(
            CopilotTaskPlanStep(
                clientStepId=f"retry_{step.client_step_id or step.step_order}",
                order=len(retry_steps) + 1,
                title=f"重试：{step.title}",
                description=f"来自失败任务 {task.title} 的安全重试步骤。",
                toolName=step.tool_name,
                toolArguments=args,
                dependencies=[],
                riskLevel=step.risk_level,  # type: ignore[arg-type]
                requiresConfirmation=step.requires_confirmation,
                waitCondition=step.wait_condition,
            )
        )
    warnings = [f"恢复来源任务：{task.title}（{task.id}）。已成功步骤不会重复执行。"]
    if not retry_steps:
        warnings.append("失败步骤包含无法确认的参数引用或无可安全自动执行步骤，请人工检查后重试原任务。")
    plan = CopilotTaskPlan(
        title=f"{task.title}恢复计划",
        goal=goal,
        summary="基于最近失败任务生成安全重试计划，不重复执行已成功步骤。",
        steps=retry_steps,
        warnings=warnings,
    )
    validate_plan(plan, auth)
    return plan


async def build_kb_then_agent_plan(db: AsyncSession, *, auth: AuthContext, goal: str) -> CopilotTaskPlan:
    kb_name = infer_kb_name(goal)
    agent_name = infer_agent_name(goal)
    model = await find_model(db, goal=goal)
    return CopilotTaskPlan(
        title=f"{kb_name}与{agent_name}搭建计划",
        goal=goal,
        summary="创建空知识库，等待用户上传资料并解析完成后，继续创建并绑定智能体。",
        steps=[
            CopilotTaskPlanStep(
                clientStepId="create_kb",
                order=1,
                title=f"创建{kb_name}",
                description="只创建空知识库，不读取本地文件。",
                toolName="knowledge_bases.create",
                toolArguments={"name": kb_name, "type": "doc_regulation", "description": f"{kb_name}，用于企业问答。"},
                riskLevel="L2",
                requiresConfirmation=True,
            ),
            CopilotTaskPlanStep(
                clientStepId="wait_kb_ready",
                order=2,
                title="等待知识库资料解析完成",
                description="如果尚无资料，任务会等待用户上传并解析完成。",
                toolName="knowledge_bases.check_readiness",
                toolArguments={"kb_id": "$steps.create_kb.knowledge_base.id"},
                dependencies=["create_kb"],
                riskLevel="L1",
                requiresConfirmation=False,
                waitCondition={
                    "type": "resource_status",
                    "resourceType": "knowledge_base",
                    "resourceIdFromStep": "create_kb",
                    "expectedStatuses": ["ready", "completed"],
                    "failureStatuses": ["failed"],
                    "timeoutSeconds": 3600,
                },
            ),
            CopilotTaskPlanStep(
                clientStepId="create_agent",
                order=3,
                title=f"创建{agent_name}并绑定知识库",
                description="知识库就绪后创建草稿并绑定。",
                toolName="agents.create_draft",
                toolArguments={
                    "name": agent_name,
                    "type": "qa",
                    "persona": build_persona(agent_name),
                    "model_id": str(model.id) if model else None,
                    "kb_ids": ["$steps.create_kb.knowledge_base.id"],
                    "tool_ids": [],
                    "config": {"temperature": 0.2, "answer_style_enabled": True},
                },
                dependencies=["wait_kb_ready"],
                riskLevel="L2",
                requiresConfirmation=True,
            ),
        ],
        warnings=["本阶段不会自动读取本地文件；请在知识库页面手动上传资料。"],
    )


async def build_preflight_plan(db: AsyncSession, *, auth: AuthContext, goal: str) -> CopilotTaskPlan:
    agent = await find_agent(db, auth=auth, goal=goal)
    if agent is None:
        raise ValidationError(code="agent_not_found", message="未找到目标智能体")
    return CopilotTaskPlan(
        title=f"{agent.name}发布前检查计划",
        goal=goal,
        summary="执行发布前检查，输出 passed/warning/blocking，不直接发布。",
        steps=[
            CopilotTaskPlanStep(
                clientStepId="preflight",
                order=1,
                title="执行发布前检查",
                description="检查模型、提示词、知识库、工具和测试状态。",
                toolName="agents.run_preflight_check",
                toolArguments={"agent_id": str(agent.id)},
                riskLevel="L1",
                requiresConfirmation=False,
            )
        ],
        warnings=["发布前检查不会自动发布智能体。"],
    )


async def build_test_then_publish_plan(db: AsyncSession, *, auth: AuthContext, goal: str) -> CopilotTaskPlan:
    agent = await find_agent(db, auth=auth, goal=goal)
    if agent is None:
        raise ValidationError(code="agent_not_found", message="未找到目标智能体")
    return CopilotTaskPlan(
        title=f"{agent.name}测试与发布准备计划",
        goal=goal,
        summary="生成并执行测试，运行发布前检查；发布步骤需要再次确认。",
        steps=[
            CopilotTaskPlanStep(
                clientStepId="generate_tests",
                order=1,
                title="生成测试问题",
                description="生成结构化测试用例。",
                toolName="agents.generate_test_cases",
                toolArguments={"agent_id": str(agent.id), "count": 5, "topic": agent.name},
                riskLevel="L1",
                requiresConfirmation=False,
            ),
            CopilotTaskPlanStep(
                clientStepId="run_tests",
                order=2,
                title="执行测试",
                description="执行测试套件并记录结果。",
                toolName="agents.run_test_suite",
                toolArguments={"agent_id": str(agent.id), "test_cases": "$steps.generate_tests.test_cases"},
                dependencies=["generate_tests"],
                riskLevel="L2",
                requiresConfirmation=True,
            ),
            CopilotTaskPlanStep(
                clientStepId="preflight",
                order=3,
                title="执行发布前检查",
                description="生成发布前检查报告。",
                toolName="agents.run_preflight_check",
                toolArguments={"agent_id": str(agent.id)},
                dependencies=["run_tests"],
                riskLevel="L1",
                requiresConfirmation=False,
            ),
            CopilotTaskPlanStep(
                clientStepId="publish",
                order=4,
                title="等待发布二次确认",
                description="发布是 L3 操作，需要你单独确认后才执行。",
                toolName="agents.publish",
                toolArguments={
                    "agent_id": str(agent.id),
                    "publish_confirmed": False,
                    "configuration_hash": "$steps.preflight.preflight.confirmation.configuration_hash",
                },
                dependencies=["preflight"],
                riskLevel="L3",
                requiresConfirmation=True,
            ),
        ],
        warnings=["确认计划不等于确认发布；最终发布会再次等待确认。"],
    )


def validate_plan(plan: CopilotTaskPlan, auth: AuthContext) -> None:
    if not plan.steps:
        return
    ids = {step.clientStepId for step in plan.steps}
    for step in plan.steps:
        tool = COPILOT_TOOL_REGISTRY.get(step.toolName)
        if tool is None:
            raise ValidationError(code="copilot_plan_tool_not_found", message=f"未注册工具：{step.toolName}")
        ensure_tool_permission(auth, tool)
        if any(dep not in ids for dep in step.dependencies):
            raise ValidationError(code="copilot_plan_invalid_dependency", message="任务依赖不存在")
        if step.riskLevel == "L3" and not step.requiresConfirmation:
            raise ValidationError(code="copilot_plan_l3_confirmation_required", message="L3 操作必须确认")
        if step.toolName in {"shell.run", "python.exec", "computer.use"}:
            raise ValidationError(code="copilot_plan_forbidden_tool", message="计划包含禁止工具")
    detect_cycle(plan.steps)


def detect_cycle(steps: list[CopilotTaskPlanStep]) -> None:
    graph = {step.clientStepId: step.dependencies for step in steps}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValidationError(code="copilot_plan_cycle", message="任务依赖存在循环")
        if node in visited:
            return
        visiting.add(node)
        for dep in graph.get(node, []):
            visit(dep)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


def pick_failed_task(candidates: list[CopilotTask], goal: str) -> CopilotTask | None:
    if not candidates:
        return None
    keywords = [item for item in ("合同", "客服", "销售", "知识库", "发布") if item in goal]
    if not keywords:
        return candidates[0]
    return next(
        (
            task
            for task in candidates
            if any(keyword in task.title or keyword in task.user_goal for keyword in keywords)
        ),
        candidates[0],
    )


def contains_unresolved_reference(value) -> bool:
    if isinstance(value, str):
        return value.startswith("$steps.")
    if isinstance(value, list):
        return any(contains_unresolved_reference(item) for item in value)
    if isinstance(value, dict):
        return any(contains_unresolved_reference(item) for item in value.values())
    return False


async def find_agent(db: AsyncSession, *, auth: AuthContext, goal: str) -> Agent | None:
    result = await db.execute(select(Agent).where(Agent.tenant_id == auth.tenant_id, Agent.status != "archived").order_by(Agent.name))
    agents = list(result.scalars().all())
    return match_name(agents, infer_agent_name(goal)) or match_name(agents, goal)


async def find_kb(db: AsyncSession, *, auth: AuthContext, goal: str) -> KnowledgeBase | None:
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.tenant_id == auth.tenant_id, KnowledgeBase.status != "archived").order_by(KnowledgeBase.name))
    kbs = list(result.scalars().all())
    return match_name(kbs, infer_kb_name(goal)) or match_name(kbs, goal)


async def find_model(db: AsyncSession, *, goal: str) -> Model | None:
    result = await db.execute(select(Model).order_by(Model.type, Model.name))
    models = list(result.scalars().all())
    return match_name(models, goal) or next((model for model in models if model.type == "llm"), models[0] if models else None)


def match_name(items, text: str):
    if not text:
        return None
    return next((item for item in items if item.name == text), None) or next(
        (item for item in items if item.name in text or text in item.name), None
    )


def infer_agent_name(goal: str) -> str:
    if "合同" in goal:
        return "合同审查助手"
    if "客服" in goal:
        return "客服助手"
    if "销售" in goal:
        return "销售助手"
    return "业务助手"


def infer_kb_name(goal: str) -> str:
    if "企业合同库" in goal:
        return "企业合同库"
    if "合同" in goal:
        return "合同知识库"
    if "客服" in goal:
        return "客服知识库"
    if "政策" in goal:
        return "政策知识库"
    return "业务知识库"


def build_persona(agent_name: str) -> str:
    return f"{agent_name}，负责基于企业知识库回答业务问题。回答需要结构清晰，优先引用企业资料；知识不足时明确说明不足。"
