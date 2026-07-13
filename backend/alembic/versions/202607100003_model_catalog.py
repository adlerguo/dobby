"""add model catalog

Revision ID: 202607100003
Revises: 202607100002
Create Date: 2026-07-10 00:03:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202607100003"
down_revision: str | None = "202607100002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        create table model_catalog (
          id uuid primary key default gen_random_uuid(),
          provider text not null,
          model_code text not null unique,
          display_name text not null,
          model_type text not null,
          description text,
          context_window integer,
          supports_streaming boolean not null default false,
          supports_tools boolean not null default false,
          supports_vision boolean not null default false,
          default_base_url text not null,
          protocol text not null,
          recommended_parameters jsonb not null default '{}',
          official_url text,
          pricing jsonb not null default '{}',
          icon text,
          sort_order integer not null default 100,
          is_active boolean not null default true,
          created_at timestamptz default now(),
          updated_at timestamptz default now()
        )
        """
    )
    op.execute("create index ix_model_catalog_provider on model_catalog(provider)")
    op.execute("create index ix_model_catalog_model_type on model_catalog(model_type)")
    op.execute("create index ix_model_catalog_is_active on model_catalog(is_active)")


def downgrade() -> None:
    op.execute("drop table if exists model_catalog")
