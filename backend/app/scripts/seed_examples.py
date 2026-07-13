import asyncio
import os
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models import Agent, AgentKb, AgentTemplate, AgentTool, Chunk, Document, KnowledgeBase, Model, Tenant, Tool, User
from app.rag.embeddings import embed_texts
from app.services import ensure_default_seed


QA_DOC = """企业合同审批需要重点检查主体资格、授权范围、付款条款、交付验收、违约责任、保密义务、数据安全、争议解决和归档要求。

审批人应核对合同金额、预算来源、印章使用、附件完整性和关键时间节点。发现风险时，应记录风险意见、明确处理人和截止时间。
"""


async def main() -> None:
    if os.getenv("SEED_DEMO_MODE", "").lower() not in {"1", "true", "yes"}:
        print("SEED_DEMO_MODE is not true; skip mock/demo example seed.")
        return
    async with SessionLocal() as db:
        await ensure_default_seed(db)
        tenant = await get_default_tenant(db)
        admin = await get_admin_user(db, tenant.id)
        chat_model = await ensure_model(db, name="mock-chat", provider="mock", type="llm")
        await ensure_model(db, name="mock-embedding", provider="mock", type="embedding")

        qa_kb = await ensure_qa_kb(db, tenant_id=tenant.id, user_id=admin.id)
        qa_agent = await ensure_agent(
            db,
            tenant_id=tenant.id,
            user_id=admin.id,
            name="示例知识问答 Agent",
            type="qa",
            model_id=chat_model.id,
            kb_ids=[qa_kb.id],
            tool_ids=[],
            persona="基于企业合同审批知识回答问题，回答时尽量给出引用。",
        )

        nl2data_tool = await ensure_nl2data_tool(db, tenant_id=tenant.id)
        nl2data_agent = await ensure_agent(
            db,
            tenant_id=tenant.id,
            user_id=admin.id,
            name="示例智能问数 Agent",
            type="nl2data",
            model_id=chat_model.id,
            kb_ids=[],
            tool_ids=[nl2data_tool.id],
            persona="你是企业智能问数助手。优先使用 12345问数 工具查询 SQLite 示例数据，回答需包含 SQL 和结果摘要。",
        )

        await db.commit()
        print(f"qa_agent_id={qa_agent.id}")
        print(f"nl2data_agent_id={nl2data_agent.id}")


async def get_default_tenant(db: AsyncSession) -> Tenant:
    result = await db.execute(select(Tenant).where(Tenant.code == "default"))
    return result.scalar_one()


async def get_admin_user(db: AsyncSession, tenant_id: UUID) -> User:
    result = await db.execute(select(User).where(User.tenant_id == tenant_id, User.username == "admin"))
    return result.scalar_one()


async def ensure_model(db: AsyncSession, *, name: str, provider: str, type: str) -> Model:
    result = await db.execute(select(Model).where(Model.name == name))
    model = result.scalar_one_or_none()
    if model is not None:
        return model
    model = Model(name=name, provider=provider, type=type)
    db.add(model)
    await db.flush()
    return model


async def ensure_qa_kb(db: AsyncSession, *, tenant_id: UUID, user_id: UUID) -> KnowledgeBase:
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.tenant_id == tenant_id, KnowledgeBase.name == "示例知识库：合同审批"))
    kb = result.scalar_one_or_none()
    if kb is None:
        kb = KnowledgeBase(
            tenant_id=tenant_id,
            name="示例知识库：合同审批",
            type="faq",
            description="T13 示例知识问答知识库",
            config={},
            embedding_model="mock-embedding",
            status="active",
            created_by=user_id,
        )
        db.add(kb)
        await db.flush()

    result = await db.execute(select(Document).where(Document.tenant_id == tenant_id, Document.kb_id == kb.id, Document.name == "合同审批要点.txt"))
    document = result.scalar_one_or_none()
    if document is None:
        document = Document(
            tenant_id=tenant_id,
            kb_id=kb.id,
            name="合同审批要点.txt",
            source_uri="seed://t13/contract-approval",
            mime="text/plain",
            size=len(QA_DOC.encode("utf-8")),
            parse_status="done",
            meta={"seed": "t13"},
        )
        db.add(document)
        await db.flush()

    result = await db.execute(select(Chunk).where(Chunk.tenant_id == tenant_id, Chunk.doc_id == document.id))
    if result.scalar_one_or_none() is None:
        parts = [part.strip() for part in QA_DOC.split("\n\n") if part.strip()]
        embeddings = await embed_texts(model="mock-embedding", texts=parts)
        for index, (content, embedding) in enumerate(zip(parts, embeddings, strict=False)):
            db.add(
                Chunk(
                    tenant_id=tenant_id,
                    kb_id=kb.id,
                    doc_id=document.id,
                    seq=index,
                    content=content,
                    tokens=len(content),
                    meta={"seed": "t13", "paragraph": index + 1},
                    embedding=embedding,
                )
            )
    return kb


async def ensure_nl2data_tool(db: AsyncSession, *, tenant_id: UUID) -> Tool:
    result = await db.execute(select(Tool).where(Tool.tenant_id == tenant_id, Tool.name == "12345问数"))
    tool = result.scalar_one_or_none()
    config = {
        "builtin": "nl2data",
        "db_path": "demo_data/12345_workorders_demo.sqlite",
        "allowed_tables": ["work_orders"],
    }
    schema = {
        "input": {
            "question": "中文问数问题，例如：按街镇统计工单量排名前5",
            "sql": "可选，只允许 SELECT/WITH 只读 SQL",
        }
    }
    if tool is None:
        tool = Tool(tenant_id=tenant_id, name="12345问数", type="builtin", schema=schema, config=config, status="active")
        db.add(tool)
    else:
        tool.schema = schema
        tool.config = config
        tool.status = "active"
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
    result = await db.execute(select(Agent).where(Agent.tenant_id == tenant_id, Agent.name == name))
    agent = result.scalar_one_or_none()
    template = (await db.execute(select(AgentTemplate).where(AgentTemplate.type == type))).scalar_one_or_none()
    config = dict(template.default_config if template is not None else {})
    config["persona"] = persona
    config["example"] = True
    if type == "nl2data":
        config["prompt"] = {
            "style": "data_answer",
            "require_sql": True,
            "catalog": "12345 work_orders SQLite demo, inspired by openchatbi catalog/table_info/sql_rule.",
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


async def replace_agent_links(db: AsyncSession, *, agent_id: UUID, kb_ids: list[UUID], tool_ids: list[UUID]) -> None:
    for existing in (await db.execute(select(AgentKb).where(AgentKb.agent_id == agent_id))).scalars().all():
        await db.delete(existing)
    for existing in (await db.execute(select(AgentTool).where(AgentTool.agent_id == agent_id))).scalars().all():
        await db.delete(existing)
    await db.flush()
    for kb_id in kb_ids:
        db.add(AgentKb(agent_id=agent_id, kb_id=kb_id))
    for tool_id in tool_ids:
        db.add(AgentTool(agent_id=agent_id, tool_id=tool_id))


if __name__ == "__main__":
    asyncio.run(main())
