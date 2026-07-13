"""publish apps and api keys

Revision ID: 202607100002
Revises: 202607100001
Create Date: 2026-07-10 00:02:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202607100002"
down_revision: str | None = "202607100001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        create table published_apps (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid not null references tenants(id),
          agent_id uuid not null references agents(id),
          name text not null,
          status text not null default 'published',
          publish_type text not null default 'api',
          config jsonb not null default '{}',
          created_by uuid,
          created_at timestamptz default now(),
          updated_at timestamptz default now()
        )
        """
    )
    op.execute("create index ix_published_apps_tenant_id on published_apps(tenant_id)")
    op.execute("create index ix_published_apps_agent_id on published_apps(agent_id)")

    op.execute(
        """
        create table app_api_keys (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid not null references tenants(id),
          app_id uuid not null references published_apps(id) on delete cascade,
          name text not null,
          key_hash text not null unique,
          key_prefix text not null,
          scopes jsonb not null default '[]',
          status text not null default 'active',
          expires_at timestamptz,
          created_by uuid,
          created_at timestamptz default now(),
          last_used_at timestamptz
        )
        """
    )
    op.execute("create index ix_app_api_keys_tenant_app on app_api_keys(tenant_id, app_id)")
    op.execute("create index ix_app_api_keys_status on app_api_keys(status)")


def downgrade() -> None:
    op.execute("drop table if exists app_api_keys")
    op.execute("drop table if exists published_apps")
