"""add name uniqueness guards

Revision ID: 202607080001
Revises: 202607070001
Create Date: 2026-07-08 21:45:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202607080001"
down_revision: str | None = "202607070001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    dedupe_active_names("agents", order_by_created_at=True)
    dedupe_active_names("knowledge_bases", order_by_created_at=True)
    dedupe_active_names("tools", order_by_created_at=False)
    dedupe_workspace_names()
    dedupe_document_names()
    dedupe_usernames()

    op.execute(
        """
        create unique index if not exists uq_agents_tenant_active_name_ci
        on agents (tenant_id, lower(btrim(name)))
        where status is distinct from 'archived'
        """
    )
    op.execute(
        """
        create unique index if not exists uq_knowledge_bases_tenant_active_name_ci
        on knowledge_bases (tenant_id, lower(btrim(name)))
        where status is distinct from 'archived'
        """
    )
    op.execute(
        """
        create unique index if not exists uq_tools_tenant_active_name_ci
        on tools (tenant_id, lower(btrim(name)))
        where status is distinct from 'archived'
        """
    )
    op.execute(
        """
        create unique index if not exists uq_workspaces_tenant_name_ci
        on workspaces (tenant_id, lower(btrim(name)))
        """
    )
    op.execute(
        """
        create unique index if not exists uq_documents_tenant_kb_name_ci
        on documents (tenant_id, kb_id, lower(btrim(name)))
        """
    )
    op.execute(
        """
        create unique index if not exists uq_users_tenant_username_ci
        on users (tenant_id, lower(btrim(username)))
        """
    )


def downgrade() -> None:
    op.execute("drop index if exists uq_users_tenant_username_ci")
    op.execute("drop index if exists uq_documents_tenant_kb_name_ci")
    op.execute("drop index if exists uq_workspaces_tenant_name_ci")
    op.execute("drop index if exists uq_tools_tenant_active_name_ci")
    op.execute("drop index if exists uq_knowledge_bases_tenant_active_name_ci")
    op.execute("drop index if exists uq_agents_tenant_active_name_ci")


def dedupe_active_names(table: str, *, order_by_created_at: bool) -> None:
    order_by = "created_at nulls last, id" if order_by_created_at else "id"
    op.execute(
        f"""
        with ranked as (
          select
            id,
            name,
            row_number() over (
              partition by tenant_id, lower(btrim(name))
              order by {order_by}
            ) as rn
          from {table}
          where status is distinct from 'archived'
        )
        update {table} target
        set name = ranked.name || ' (重复 ' || ranked.rn || ')'
        from ranked
        where target.id = ranked.id and ranked.rn > 1
        """
    )


def dedupe_workspace_names() -> None:
    op.execute(
        """
        with ranked as (
          select
            id,
            name,
            row_number() over (
              partition by tenant_id, lower(btrim(name))
              order by created_at nulls last, id
            ) as rn
          from workspaces
        )
        update workspaces target
        set name = ranked.name || ' (重复 ' || ranked.rn || ')'
        from ranked
        where target.id = ranked.id and ranked.rn > 1
        """
    )


def dedupe_document_names() -> None:
    op.execute(
        """
        with ranked as (
          select
            id,
            name,
            row_number() over (
              partition by tenant_id, kb_id, lower(btrim(name))
              order by created_at nulls last, id
            ) as rn
          from documents
        )
        update documents target
        set name = ranked.name || ' (重复 ' || ranked.rn || ')'
        from ranked
        where target.id = ranked.id and ranked.rn > 1
        """
    )


def dedupe_usernames() -> None:
    op.execute(
        """
        with ranked as (
          select
            id,
            username,
            row_number() over (
              partition by tenant_id, lower(btrim(username))
              order by created_at nulls last, id
            ) as rn
          from users
        )
        update users target
        set username = ranked.username || '_duplicate_' || ranked.rn
        from ranked
        where target.id = ranked.id and ranked.rn > 1
        """
    )
