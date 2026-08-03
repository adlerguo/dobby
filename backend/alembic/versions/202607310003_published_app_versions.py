"""add published app versions

Revision ID: 202607310003
Revises: 202607310002
Create Date: 2026-07-31 00:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202607310003"
down_revision: str | None = "202607310002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("alter table published_apps add column if not exists active_version_id uuid null")
    op.execute(
        """
        create table if not exists published_app_versions (
          id uuid primary key,
          tenant_id uuid not null,
          app_id uuid not null references published_apps(id),
          agent_id uuid not null references agents(id),
          version_no integer not null,
          status text not null default 'active',
          title text null,
          release_note text null,
          snapshot jsonb not null default '{}'::jsonb,
          precheck_result jsonb not null default '{}'::jsonb,
          created_by uuid null references users(id),
          created_at timestamptz not null default now(),
          activated_at timestamptz null
        )
        """
    )
    op.execute(
        """
        create unique index if not exists uq_published_app_versions_tenant_app_no
        on published_app_versions (tenant_id, app_id, version_no)
        """
    )
    op.execute(
        """
        create index if not exists ix_published_app_versions_tenant_app_status
        on published_app_versions (tenant_id, app_id, status)
        """
    )
    op.execute(
        """
        create unique index if not exists uq_published_app_versions_tenant_app_active
        on published_app_versions (tenant_id, app_id)
        where status = 'active'
        """
    )
    op.execute(
        """
        insert into published_app_versions (
          id, tenant_id, app_id, agent_id, version_no, status, title, release_note,
          snapshot, precheck_result, created_by, created_at, activated_at
        )
        select
          gen_random_uuid(),
          p.tenant_id,
          p.id,
          p.agent_id,
          1,
          'active',
          'v1',
          '历史发布自动生成',
          jsonb_build_object(
            'schema_version', 'm5_v1',
            'created_from', 'migration',
            'agent', jsonb_build_object(
              'id', a.id::text,
              'name', a.name,
              'type', a.type,
              'persona', a.persona,
              'config', coalesce(a.config, '{}'::jsonb),
              'model_id', a.model_id::text
            ),
            'kb_ids', '[]'::jsonb,
            'tool_ids', '[]'::jsonb,
            'model', '{}'::jsonb,
            'published_app_config', coalesce(p.config, '{}'::jsonb)
          ),
          jsonb_build_object('status', 'warning', 'checks', jsonb_build_array(jsonb_build_object(
            'check', 'historical_snapshot',
            'status', 'warning',
            'level', 'warning',
            'message', '历史迁移快照无法精确恢复 kb_ids/tool_ids'
          ))),
          p.created_by,
          p.created_at,
          p.created_at
        from published_apps p
        join agents a on a.id = p.agent_id
        where not exists (
          select 1 from published_app_versions v
          where v.tenant_id = p.tenant_id and v.app_id = p.id and v.version_no = 1
        )
        """
    )
    op.execute(
        """
        update published_apps p
        set active_version_id = v.id
        from published_app_versions v
        where v.app_id = p.id
          and v.tenant_id = p.tenant_id
          and v.status = 'active'
          and p.active_version_id is null
        """
    )


def downgrade() -> None:
    op.execute("alter table published_apps drop column if exists active_version_id")
    op.execute("drop index if exists uq_published_app_versions_tenant_app_active")
    op.execute("drop index if exists ix_published_app_versions_tenant_app_status")
    op.execute("drop index if exists uq_published_app_versions_tenant_app_no")
    op.execute("drop table if exists published_app_versions")
