from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


CONSTRAINT_DETAIL_MAP = {
    "uq_agents_tenant_active_name_ci": "agent_name_exists",
    "uq_knowledge_bases_tenant_active_name_ci": "kb_name_exists",
    "uq_tools_tenant_active_name_ci": "tool_name_exists",
    "uq_workspaces_tenant_name_ci": "workspace_name_exists",
    "uq_documents_tenant_kb_name_ci": "document_name_exists",
    "uq_documents_tenant_kb_logical_version": "document_version_exists",
    "uq_documents_tenant_kb_logical_active": "document_active_version_exists",
    "uq_users_tenant_username_ci": "username_exists",
}


def normalize_unique_text(value: str) -> str:
    return value.strip().lower()


async def ensure_tenant_name_available(
    db: AsyncSession,
    *,
    model: type,
    tenant_id: UUID,
    name: str,
    detail: str,
    exclude_id: UUID | None = None,
    ignore_archived: bool = True,
) -> None:
    stmt = select(model.id).where(
        model.tenant_id == tenant_id,
        func.lower(func.btrim(model.name)) == normalize_unique_text(name),
    )
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    if ignore_archived and hasattr(model, "status"):
        stmt = stmt.where(model.status.is_distinct_from("archived"))

    result = await db.execute(stmt.limit(1))
    if result.scalar_one_or_none() is not None:
        raise ValueError(detail)


async def ensure_document_name_available(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    kb_id: UUID,
    name: str,
    exclude_id: UUID | None = None,
) -> None:
    from app.models import Document

    stmt = select(Document.id).where(
        Document.tenant_id == tenant_id,
        Document.kb_id == kb_id,
        func.lower(func.btrim(Document.name)) == normalize_unique_text(name),
    )
    if hasattr(Document, "version_status"):
        stmt = stmt.where(Document.version_status == "active")
    if exclude_id is not None:
        stmt = stmt.where(Document.id != exclude_id)

    result = await db.execute(stmt.limit(1))
    if result.scalar_one_or_none() is not None:
        raise ValueError("document_name_exists")


def detail_from_integrity_error(exc: IntegrityError, fallback: str) -> str:
    constraint = getattr(getattr(exc, "orig", None), "diag", None)
    constraint_name = getattr(constraint, "constraint_name", None)
    if constraint_name in CONSTRAINT_DETAIL_MAP:
        return CONSTRAINT_DETAIL_MAP[constraint_name]
    return fallback
