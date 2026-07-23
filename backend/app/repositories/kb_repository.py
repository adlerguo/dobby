from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, KnowledgeBase
from app.repositories.base import TenantRepository


class KnowledgeBaseRepository(TenantRepository[KnowledgeBase]):
    model = KnowledgeBase

    async def list_by_type(self, type: str | None = None) -> Sequence[KnowledgeBase]:
        stmt = self.query().order_by(KnowledgeBase.created_at.desc())
        if type is not None:
            stmt = stmt.where(KnowledgeBase.type == type)
        result = await self.db.execute(stmt)
        return result.scalars().all()


class DocumentRepository(TenantRepository[Document]):
    model = Document

    async def list_by_kb(self, kb_id: UUID) -> Sequence[Document]:
        result = await self.db.execute(
            self.query()
            .where(Document.kb_id == kb_id)
            .order_by(Document.created_at.desc())
        )
        return result.scalars().all()

    async def get_by_id_and_kb(self, document_id: UUID, kb_id: UUID) -> Document | None:
        result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.kb_id == kb_id,
                Document.tenant_id == self.tenant_id,
            )
        )
        return result.scalar_one_or_none()
