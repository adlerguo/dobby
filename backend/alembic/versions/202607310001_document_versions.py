"""add lightweight document versions

Revision ID: 202607310001
Revises: 202607220001
Create Date: 2026-07-31 00:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202607310001"
down_revision: str | None = "202607220001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("drop index if exists uq_documents_tenant_kb_name_ci")
    op.execute(
        """
        alter table documents
          add column if not exists logical_doc_id uuid,
          add column if not exists version_no integer not null default 1,
          add column if not exists version_status text not null default 'active',
          add column if not exists version_parent_id uuid null references documents(id),
          add column if not exists activated_at timestamptz null
        """
    )
    op.execute(
        """
        update documents
        set
          logical_doc_id = coalesce(logical_doc_id, id),
          version_no = coalesce(version_no, 1),
          version_status = coalesce(version_status, 'active'),
          activated_at = coalesce(activated_at, created_at)
        where logical_doc_id is null
           or version_no is null
           or version_status is null
           or activated_at is null
        """
    )
    op.execute("alter table documents alter column logical_doc_id set not null")
    op.execute(
        """
        create unique index if not exists uq_documents_tenant_kb_name_ci
        on documents (tenant_id, kb_id, lower(btrim(name)))
        where version_status = 'active'
        """
    )
    op.execute(
        """
        create unique index if not exists uq_documents_tenant_kb_logical_version
        on documents (tenant_id, kb_id, logical_doc_id, version_no)
        """
    )
    op.execute(
        """
        create unique index if not exists uq_documents_tenant_kb_logical_active
        on documents (tenant_id, kb_id, logical_doc_id)
        where version_status = 'active'
        """
    )
    op.execute(
        """
        create index if not exists ix_documents_tenant_kb_logical_doc
        on documents (tenant_id, kb_id, logical_doc_id, version_no desc)
        """
    )


def downgrade() -> None:
    op.execute("drop index if exists ix_documents_tenant_kb_logical_doc")
    op.execute("drop index if exists uq_documents_tenant_kb_logical_active")
    op.execute("drop index if exists uq_documents_tenant_kb_logical_version")
    op.execute("drop index if exists uq_documents_tenant_kb_name_ci")
    op.execute(
        """
        create unique index if not exists uq_documents_tenant_kb_name_ci
        on documents (tenant_id, kb_id, lower(btrim(name)))
        """
    )
    op.execute(
        """
        alter table documents
          drop column if exists activated_at,
          drop column if exists version_parent_id,
          drop column if exists version_status,
          drop column if exists version_no,
          drop column if exists logical_doc_id
        """
    )
