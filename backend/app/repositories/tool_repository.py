from collections.abc import Sequence

from app.models import Tool
from app.repositories.base import TenantRepository


class ToolRepository(TenantRepository[Tool]):
    model = Tool

    async def list_active(self) -> Sequence[Tool]:
        result = await self.db.execute(
            self.query().where(Tool.status == "active").order_by(Tool.name)
        )
        return result.scalars().all()
