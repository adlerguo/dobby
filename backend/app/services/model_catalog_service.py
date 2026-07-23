from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModelCatalog


async def list_model_catalog(
    db: AsyncSession,
    *,
    model_type: str | None = None,
    provider: str | None = None,
) -> list[ModelCatalog]:
    stmt = select(ModelCatalog).where(ModelCatalog.is_active.is_(True))
    if model_type:
        stmt = stmt.where(ModelCatalog.model_type == model_type)
    if provider:
        stmt = stmt.where(ModelCatalog.provider == provider)
    stmt = stmt.order_by(
        ModelCatalog.sort_order.asc(),
        ModelCatalog.provider.asc(),
        ModelCatalog.model_code.asc(),
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_model_catalog_item(
    db: AsyncSession, catalog_id: UUID
) -> ModelCatalog | None:
    result = await db.execute(
        select(ModelCatalog).where(
            ModelCatalog.id == catalog_id, ModelCatalog.is_active.is_(True)
        )
    )
    return result.scalar_one_or_none()
