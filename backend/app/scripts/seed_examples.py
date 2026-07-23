import asyncio
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models import (
    Agent,
    AgentKb,
    AgentTemplate,
    AgentTool,
    Chunk,
    Document,
    KnowledgeBase,
    Model,
    Tenant,
    Tool,
    User,
)
from app.scripts.sync_guide_to_kb import sync_guide_to_kb
from app.services import ensure_default_seed


PURE_PROMPT_EXAMPLES: tuple[dict[str, str], ...] = (
    {
        "type": "paper_explainer",
        "name": "论文速读",
        "persona": "你是学术导师，擅长把论文讲给非专业听众。收到论文标题与摘要（或正文）后：①5 句以内总结核心发现；②不超过 6 行通俗解释方法；③列 3 个可能局限与 2 个可行后续研究问题；④若含实验数据，指出需核实的关键指标（样本量、对照组、显著性等）。",
    },
    {
        "type": "data_detective",
        "name": "数据侦探",
        "persona": "你是数据分析师。用户会上传 CSV 或粘贴示例数据。①列 5 个关键数据质量问题（缺失、异常值、重复等）；②给 5 个可验证假设，每个对应具体统计检验或可视化；③给 3 个推荐图表（标题+x轴+y轴+图表类型）。收到数据前先回应'准备好接收数据'并说明所需最大行列数。",
    },
    {
        "type": "mock_interviewer",
        "name": "超级面试官",
        "persona": "你是面试官，对指定岗位做模拟面试（默认全栈工程师，可切换产品经理/数据科学家等）。①从 3 个行为类 + 3 个技术类问题开始；②每题给'理想答案要点'与'常见错误'；③每轮问答后给 1-2 条可执行改进建议（含具体词句）。开场先问一个 1-2 分钟的开放式自我介绍。",
    },
    {
        "type": "writing_muse",
        "name": "写作灵感伴侣",
        "persona": "你是写作灵感伴侣，帮助创作短篇、小说片段、剧本对白或改写风格。用户给出目标、风格与设定后，用感官细节呈现场景、注意语言节奏与音乐感，并在需要时留下悬念结尾。",
    },
    {
        "type": "study_planner",
        "name": "学习计划教练",
        "persona": "你是学习教练。根据用户的目标、周期与每周可用时间：①制定分周学习计划（周目标 + 每日任务时间分配）；②给出复习策略（间隔重复：哪些内容何时复习）；③推荐 6 个优质学习资源。",
    },
    {
        "type": "brand_namer",
        "name": "创意命名师",
        "persona": "你是品牌命名专家。根据产品与目标用户：①生成 20 个候选名（标注发音难度与域名可用性建议）；②选 5 个最优并解释理由（语义、可记忆性、行业匹配）；③提示商标/域名初查需注意的三件事。（非法律意见）",
    },
    {
        "type": "prompt_engineer",
        "name": "提示工程师",
        "persona": "你是高级提示工程师，帮用户把一个想法做成可复用的 agent。①给出完整 system 指令、用户初始 prompt、两个示例对话；②给 3 条可选约束（输出长度上限、优先安全、语言简洁）；③一句话说明如何接入常见 Agent 框架。",
    },
)

EXAMPLE_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "HTTP API 调用器（天气查询）",
        "type": "http",
        "schema": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "城市名称"}},
            "required": ["city"],
        },
        "config": {
            "category": "capability",
            "group": "api_call",
            "audience": "agent",
            "availability": "active",
            "icon": "link",
            "summary": "调用外部 HTTP 接口获取数据，示例为按城市查询天气。",
            "http": {
                "method": "GET",
                "url": "https://api.example.com/weather?city={city}",
                "headers": {},
            },
            "method": "GET",
            "url": "https://api.example.com/weather?city={city}",
            "headers": {},
        },
    },
    {
        "name": "计算器 / 表达式求值",
        "type": "code",
        "schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "要计算的数学表达式"}
            },
            "required": ["expression"],
        },
        "config": {
            "category": "capability",
            "group": "compute",
            "audience": "agent",
            "availability": "active",
            "icon": "cpu",
            "summary": "对数学表达式进行求值，供智能体做即时计算。",
            "builtin": "code",
        },
    },
    {
        "name": "网页搜索",
        "type": "builtin",
        "schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "搜索关键词"}},
            "required": ["query"],
        },
        "config": {
            "category": "capability",
            "group": "retrieval",
            "audience": "agent",
            "availability": "coming_soon",
            "icon": "search",
            "summary": "联网检索公开信息，为回答补充实时资料。（即将支持执行）",
        },
    },
    {
        "name": "知识库检索",
        "type": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "kb_id": {"type": "string", "description": "知识库 ID，可留空表示默认"},
                "query": {"type": "string", "description": "检索问题"},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
        "config": {
            "category": "capability",
            "group": "retrieval",
            "audience": "agent",
            "availability": "active",
            "icon": "collection",
            "summary": "检索指定知识库，让智能体像调用工具一样获取企业资料与引用。",
            "builtin": "kb_retrieval",
        },
    },
    {
        "name": "地图定位",
        "type": "http",
        "schema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["geocode", "poi", "route"],
                    "description": "地理编码/地点搜索/路线",
                },
                "query": {
                    "type": "string",
                    "description": "地址或关键词（geocode/poi 用）",
                },
                "origin": {"type": "string"},
                "destination": {"type": "string"},
            },
            "required": ["mode"],
        },
        "config": {
            "category": "capability",
            "group": "map",
            "audience": "agent",
            "availability": "coming_soon",
            "icon": "location",
            "summary": "提供地理编码、地点搜索与路线距离，支撑“附近有什么、怎么走”类问答。请先配置地图服务 Key。（即将支持执行）",
            "http": {"method": "GET", "url": "", "headers": {}},
            "method": "GET",
            "url": "",
            "headers": {},
        },
    },
    {
        "name": "MCP 连接（示例）",
        "type": "mcp",
        "schema": {},
        "config": {
            "category": "capability",
            "group": "mcp",
            "audience": "agent",
            "availability": "coming_soon",
            "icon": "plug",
            "summary": "按 MCP 标准连接你自己的 MCP Server，或用对话式构建生成能力。请在详情中填写 Server 信息。（即将支持执行）",
            "mcp": {
                "name": "示例 MCP Server",
                "transport": "sse",
                "server_url": "",
                "auth": {"type": "none"},
            },
        },
    },
    {
        "name": "模型连通性检测",
        "type": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "model_id": {
                    "type": "string",
                    "description": "要检测的模型 ID，可留空检测全部已启用模型",
                }
            },
        },
        "config": {
            "category": "ops",
            "group": "connectivity",
            "audience": "admin",
            "availability": "active",
            "icon": "connection",
            "summary": "检测已接入模型的连通状态，快速定位不可用的模型。",
            "builtin": "model_connectivity",
        },
    },
    {
        "name": "知识库重建索引",
        "type": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "kb_id": {"type": "string", "description": "要重建索引的知识库 ID"}
            },
            "required": ["kb_id"],
        },
        "config": {
            "category": "ops",
            "group": "data_admin",
            "audience": "admin",
            "availability": "coming_soon",
            "icon": "refresh",
            "summary": "对指定知识库重新切片与向量化，修复检索质量问题。（即将支持执行）",
        },
    },
    {
        "name": "审计 / 用量导出",
        "type": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "start": {"type": "string", "description": "开始日期 YYYY-MM-DD"},
                "end": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
                "format": {"type": "string", "enum": ["csv", "xlsx"], "default": "csv"},
            },
            "required": ["start", "end"],
        },
        "config": {
            "category": "ops",
            "group": "export",
            "audience": "admin",
            "availability": "coming_soon",
            "icon": "download",
            "summary": "按时间段导出审计日志与用量统计，供合规与运营分析。（即将支持执行）",
        },
    },
)


async def main() -> None:
    async with SessionLocal() as db:
        await ensure_default_seed(db)
        tenant = await get_default_tenant(db)
        admin = await get_admin_user(db, tenant.id)
        chat_model = await ensure_model(
            db, name="mock-chat", provider="mock", type="llm"
        )
        await ensure_model(db, name="mock-embedding", provider="mock", type="embedding")

        await remove_legacy_examples(db, tenant_id=tenant.id)

        created_agents: list[Agent] = []
        for example in PURE_PROMPT_EXAMPLES:
            created_agents.append(
                await ensure_agent(
                    db,
                    tenant_id=tenant.id,
                    user_id=admin.id,
                    name=example["name"],
                    type=example["type"],
                    model_id=chat_model.id,
                    kb_ids=[],
                    tool_ids=[],
                    persona=example["persona"],
                )
            )

        tutorial_kb = await ensure_tutorial_kb(
            db, tenant_id=tenant.id, user_id=admin.id
        )
        created_agents.append(
            await ensure_agent(
                db,
                tenant_id=tenant.id,
                user_id=admin.id,
                name="使用教程问答",
                type="qa",
                model_id=chat_model.id,
                kb_ids=[tutorial_kb.id],
                tool_ids=[],
                persona="你是平台使用教程问答助手。请基于“平台使用教程”知识库作答；回答先给出结论，再列出清晰步骤，并在涉及具体功能时给出引用。若教程中没有相关内容，请说明当前教程未覆盖，并建议用户查看对应页面。",
            )
        )

        nl2data_tool = await ensure_nl2data_tool(db, tenant_id=tenant.id)
        example_tools = [
            nl2data_tool,
            *(await ensure_example_tools(db, tenant_id=tenant.id)),
        ]
        created_agents.append(
            await ensure_agent(
                db,
                tenant_id=tenant.id,
                user_id=admin.id,
                name="智能问数",
                type="nl2data",
                model_id=chat_model.id,
                kb_ids=[],
                tool_ids=[nl2data_tool.id],
                persona="你是企业智能问数助手。优先使用 12345问数 工具查询示例业务库；回答需展示 SQL、结果摘要和可读的数据解读，并提醒用户仅基于当前示例数据判断。",
            )
        )

        await db.commit()
        print(
            "seeded_example_agents="
            + ",".join(f"{agent.name}:{agent.id}" for agent in created_agents)
        )
        print(f"tutorial_kb_id={tutorial_kb.id}")
        print(f"nl2data_tool_id={nl2data_tool.id}")
        print(
            "seeded_example_tools="
            + ",".join(f"{tool.name}:{tool.id}" for tool in example_tools)
        )


async def get_default_tenant(db: AsyncSession) -> Tenant:
    result = await db.execute(select(Tenant).where(Tenant.code == "default"))
    return result.scalar_one()


async def get_admin_user(db: AsyncSession, tenant_id: UUID) -> User:
    result = await db.execute(
        select(User).where(User.tenant_id == tenant_id, User.username == "admin")
    )
    return result.scalar_one()


async def ensure_model(
    db: AsyncSession, *, name: str, provider: str, type: str
) -> Model:
    result = await db.execute(select(Model).where(Model.name == name))
    model = result.scalar_one_or_none()
    if model is not None:
        return model
    model = Model(name=name, provider=provider, type=type)
    db.add(model)
    await db.flush()
    return model


async def remove_legacy_examples(db: AsyncSession, *, tenant_id: UUID) -> None:
    legacy_agent_names = ["示例知识问答 Agent", "示例智能问数 Agent"]
    legacy_agents = (
        (
            await db.execute(
                select(Agent).where(
                    Agent.tenant_id == tenant_id, Agent.name.in_(legacy_agent_names)
                )
            )
        )
        .scalars()
        .all()
    )
    for agent in legacy_agents:
        await db.execute(delete(AgentKb).where(AgentKb.agent_id == agent.id))
        await db.execute(delete(AgentTool).where(AgentTool.agent_id == agent.id))
        await db.delete(agent)

    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.tenant_id == tenant_id,
            KnowledgeBase.name == "示例知识库：合同审批",
        )
    )
    legacy_kb = result.scalar_one_or_none()
    if legacy_kb is not None:
        documents = (
            (
                await db.execute(
                    select(Document).where(
                        Document.tenant_id == tenant_id, Document.kb_id == legacy_kb.id
                    )
                )
            )
            .scalars()
            .all()
        )
        for document in documents:
            await db.execute(
                delete(Chunk).where(
                    Chunk.tenant_id == tenant_id, Chunk.doc_id == document.id
                )
            )
            await db.delete(document)
        await db.delete(legacy_kb)
    await db.flush()


async def ensure_tutorial_kb(
    db: AsyncSession, *, tenant_id: UUID, user_id: UUID
) -> KnowledgeBase:
    return await sync_guide_to_kb(db, tenant_id=tenant_id, user_id=user_id)


async def ensure_nl2data_tool(db: AsyncSession, *, tenant_id: UUID) -> Tool:
    config = {
        "category": "capability",
        "group": "data_query",
        "audience": "agent",
        "availability": "active",
        "icon": "data-analysis",
        "summary": "用自然语言查询业务数据，自动生成 SQL 并返回结果。",
        "builtin": "nl2data",
        "db_path": "demo_data/12345_workorders_demo.sqlite",
        "allowed_tables": ["work_orders"],
    }
    schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "中文问数问题，例如：按街镇统计工单量排名前5",
            },
            "sql": {
                "type": "string",
                "description": "可选，只允许 SELECT/WITH 只读 SQL",
            },
        },
        "required": ["question"],
    }
    return await ensure_tool(
        db,
        tenant_id=tenant_id,
        name="12345问数",
        type="builtin",
        schema=schema,
        config=config,
    )


async def ensure_example_tools(db: AsyncSession, *, tenant_id: UUID) -> list[Tool]:
    tools: list[Tool] = []
    for item in EXAMPLE_TOOL_DEFINITIONS:
        tools.append(
            await ensure_tool(
                db,
                tenant_id=tenant_id,
                name=item["name"],
                type=item["type"],
                schema=item["schema"],
                config=item["config"],
            )
        )
    return tools


async def ensure_tool(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    name: str,
    type: str,
    schema: dict[str, Any],
    config: dict[str, Any],
    status: str = "active",
) -> Tool:
    result = await db.execute(
        select(Tool).where(Tool.tenant_id == tenant_id, Tool.name == name)
    )
    tool = result.scalar_one_or_none()
    if tool is None:
        tool = Tool(
            tenant_id=tenant_id,
            name=name,
            type=type,
            schema=schema,
            config=config,
            status=status,
        )
        db.add(tool)
    else:
        tool.type = type
        tool.schema = schema
        tool.config = config
        tool.status = status
    await db.flush()
    return tool


async def ensure_agent(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    name: str,
    type: str,
    model_id: UUID,
    kb_ids: list[UUID],
    tool_ids: list[UUID],
    persona: str,
) -> Agent:
    result = await db.execute(
        select(Agent).where(Agent.tenant_id == tenant_id, Agent.name == name)
    )
    agent = result.scalar_one_or_none()
    template = (
        await db.execute(select(AgentTemplate).where(AgentTemplate.type == type))
    ).scalar_one_or_none()
    config = dict(template.default_config if template is not None else {})
    config["persona"] = persona
    config["example"] = True
    config["ui"] = config.get("ui") or {}
    if type == "qa":
        config["prompt"] = {"style": "grounded_steps", "require_citations": True}
        config["retrieval"] = {"top_k": 5, "score_threshold": 0.2}
    if type == "nl2data":
        config["prompt"] = {
            "style": "data_answer",
            "require_sql": True,
            "catalog": "12345 work_orders SQLite demo, inspired by openchatbi catalog/table_info/sql_rule.",
        }
        config["ui"] = {
            "category": "工具调用",
            "description": "查询 12345 示例业务库，自动生成 SQL、结果摘要和数据解读。",
            "sample_questions": [
                "按街镇统计工单量排名前 5。",
                "最近每月工单量趋势如何？",
                "按主责部门统计工单量排名前 10。",
            ],
        }
    if agent is None:
        agent = Agent(
            tenant_id=tenant_id,
            name=name,
            type=type,
            template_id=template.id if template is not None else None,
            persona=persona,
            config=config,
            model_id=model_id,
            status="active",
            created_by=user_id,
        )
        db.add(agent)
        await db.flush()
    else:
        agent.type = type
        agent.template_id = template.id if template is not None else None
        agent.persona = persona
        agent.config = config
        agent.model_id = model_id
        agent.status = "active"

    await replace_agent_links(db, agent_id=agent.id, kb_ids=kb_ids, tool_ids=tool_ids)
    return agent


async def replace_agent_links(
    db: AsyncSession, *, agent_id: UUID, kb_ids: list[UUID], tool_ids: list[UUID]
) -> None:
    await db.execute(delete(AgentKb).where(AgentKb.agent_id == agent_id))
    await db.execute(delete(AgentTool).where(AgentTool.agent_id == agent_id))
    await db.flush()
    for kb_id in kb_ids:
        db.add(AgentKb(agent_id=agent_id, kb_id=kb_id))
    for tool_id in tool_ids:
        db.add(AgentTool(agent_id=agent_id, tool_id=tool_id))


if __name__ == "__main__":
    asyncio.run(main())
