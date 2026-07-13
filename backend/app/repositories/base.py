from collections.abc import Sequence
from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class Repository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def query(self) -> Select[tuple[ModelT]]:
        return select(self.model)

    async def get_by_id(self, id: UUID) -> ModelT | None:
        result = await self.db.execute(self.query().where(self.model.id == id))
        return result.scalar_one_or_none()

    async def list(self, *, offset: int = 0, limit: int = 20) -> Sequence[ModelT]:
        result = await self.db.execute(self.query().offset(offset).limit(limit))
        return result.scalars().all()

    async def add(self, obj: ModelT) -> ModelT:
        self.db.add(obj)
        await self.db.flush()
        return obj


class TenantRepository(Repository[ModelT]):
    def __init__(self, db: AsyncSession, tenant_id: UUID) -> None:
        super().__init__(db)
        self.tenant_id = tenant_id

    def query(self) -> Select[tuple[ModelT]]:
        if not hasattr(self.model, "tenant_id"):
            raise TypeError(f"{self.model.__name__} is not tenant scoped")
        return select(self.model).where(self.model.tenant_id == self.tenant_id)

    async def get_by_id(self, id: UUID) -> ModelT | None:
        result = await self.db.execute(self.query().where(self.model.id == id))
        return result.scalar_one_or_none()

    async def add(self, obj: ModelT) -> ModelT:
        if not hasattr(obj, "tenant_id"):
            raise TypeError(f"{self.model.__name__} is not tenant scoped")

        obj_tenant_id = getattr(obj, "tenant_id", None)
        if obj_tenant_id is None:
            setattr(obj, "tenant_id", self.tenant_id)
        elif obj_tenant_id != self.tenant_id:
            raise ValueError("tenant_id_mismatch")

        self.db.add(obj)
        await self.db.flush()
        return obj

    async def update_by_id(self, id: UUID, values: dict[str, Any]) -> ModelT | None:
        obj = await self.get_by_id(id)
        if obj is None:
            return None

        values.pop("tenant_id", None)
        for key, value in values.items():
            setattr(obj, key, value)

        await self.db.flush()
        return obj
