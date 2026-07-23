from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select

from app.models import Agent, AgentKb, AgentTool
from app.repositories.base import TenantRepository


class AgentRepository(TenantRepository[Agent]):
    model = Agent

    async def list_by_status(self, status: str | None = None) -> Sequence[Agent]:
        stmt = self.query().order_by(Agent.created_at.desc())
        if status is not None:
            stmt = stmt.where(Agent.status == status)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def replace_kbs(self, agent_id: UUID, kb_ids: list[UUID]) -> None:
        await self.db.execute(delete(AgentKb).where(AgentKb.agent_id == agent_id))
        for kb_id in kb_ids:
            self.db.add(AgentKb(agent_id=agent_id, kb_id=kb_id))

    async def replace_tools(self, agent_id: UUID, tool_ids: list[UUID]) -> None:
        await self.db.execute(delete(AgentTool).where(AgentTool.agent_id == agent_id))
        for tool_id in tool_ids:
            self.db.add(AgentTool(agent_id=agent_id, tool_id=tool_id))

    async def get_kb_ids(self, agent_id: UUID) -> list[UUID]:
        result = await self.db.execute(
            select(AgentKb.kb_id).where(AgentKb.agent_id == agent_id)
        )
        return list(result.scalars().all())

    async def get_tool_ids(self, agent_id: UUID) -> list[UUID]:
        result = await self.db.execute(
            select(AgentTool.tool_id).where(AgentTool.agent_id == agent_id)
        )
        return list(result.scalars().all())
