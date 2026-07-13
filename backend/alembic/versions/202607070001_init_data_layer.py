"""init data layer

Revision ID: 202607070001
Revises:
Create Date: 2026-07-07 00:01:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202607070001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("create extension if not exists pgcrypto")
    op.execute("create extension if not exists vector")

    op.execute(
        """
        create table tenants (
          id uuid primary key default gen_random_uuid(),
          name text not null,
          code text unique not null,
          status text not null default 'active',
          created_at timestamptz default now(),
          updated_at timestamptz default now()
        )
        """
    )
    op.execute(
        """
        create table users (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid not null references tenants(id),
          username text not null,
          password_hash text not null,
          display_name text,
          email text,
          status text default 'active',
          created_at timestamptz default now(),
          updated_at timestamptz default now(),
          unique(tenant_id, username)
        )
        """
    )
    op.execute(
        """
        create table roles (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid not null references tenants(id),
          name text not null,
          code text not null,
          unique(tenant_id, code)
        )
        """
    )
    op.execute(
        """
        create table permissions (
          id uuid primary key default gen_random_uuid(),
          code text unique not null,
          name text,
          module text
        )
        """
    )
    op.execute(
        """
        create table user_roles (
          user_id uuid references users(id),
          role_id uuid references roles(id),
          primary key(user_id, role_id)
        )
        """
    )
    op.execute(
        """
        create table role_permissions (
          role_id uuid references roles(id),
          permission_id uuid references permissions(id),
          primary key(role_id, permission_id)
        )
        """
    )

    op.execute(
        """
        create table knowledge_bases (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid not null references tenants(id),
          name text not null,
          type text not null,
          description text,
          config jsonb default '{}',
          embedding_model text default 'text-embedding-3-small',
          status text default 'active',
          created_by uuid,
          created_at timestamptz default now(),
          updated_at timestamptz default now()
        )
        """
    )
    op.execute(
        """
        create table documents (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid not null,
          kb_id uuid not null references knowledge_bases(id),
          name text not null,
          source_uri text,
          mime text,
          size bigint,
          parse_status text default 'pending',
          meta jsonb default '{}',
          created_at timestamptz default now()
        )
        """
    )
    op.execute(
        """
        create table chunks (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid not null,
          kb_id uuid not null references knowledge_bases(id),
          doc_id uuid not null references documents(id),
          seq int,
          content text not null,
          tokens int,
          meta jsonb default '{}',
          embedding vector(1536),
          created_at timestamptz default now()
        )
        """
    )
    op.execute("create index ix_chunks_embedding on chunks using hnsw (embedding vector_cosine_ops)")
    op.execute("create index ix_chunks_kb_id on chunks (kb_id)")
    op.execute("create index chunks_content_fts on chunks using gin (to_tsvector('simple', content))")

    op.execute(
        """
        create table agent_templates (
          id uuid primary key default gen_random_uuid(),
          type text not null,
          name text not null,
          default_config jsonb default '{}',
          builtin bool default true
        )
        """
    )
    op.execute(
        """
        create table agents (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid not null,
          name text not null,
          type text not null,
          template_id uuid references agent_templates(id),
          persona text,
          config jsonb default '{}',
          model_id uuid,
          status text default 'draft',
          created_by uuid,
          created_at timestamptz default now(),
          updated_at timestamptz default now()
        )
        """
    )
    op.execute(
        """
        create table tools (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid not null,
          name text not null,
          type text not null,
          schema jsonb default '{}',
          config jsonb default '{}',
          status text default 'active'
        )
        """
    )
    op.execute(
        """
        create table agent_tools (
          agent_id uuid references agents(id),
          tool_id uuid references tools(id),
          primary key(agent_id, tool_id)
        )
        """
    )
    op.execute(
        """
        create table agent_kbs (
          agent_id uuid references agents(id),
          kb_id uuid references knowledge_bases(id),
          primary key(agent_id, kb_id)
        )
        """
    )
    op.execute(
        """
        create table models (
          id uuid primary key default gen_random_uuid(),
          name text unique not null,
          provider text,
          type text not null
        )
        """
    )
    op.execute(
        """
        create table model_channels (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid,
          model_id uuid references models(id),
          base_url text not null,
          api_key_enc text not null,
          weight int default 1,
          rpm_limit int,
          status text default 'active',
          health text default 'unknown',
          created_at timestamptz default now()
        )
        """
    )
    op.execute(
        """
        create table api_keys (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid not null,
          name text,
          key_hash text not null,
          scopes jsonb default '[]',
          status text default 'active'
        )
        """
    )

    op.execute(
        """
        create table conversations (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid not null,
          user_id uuid,
          agent_id uuid,
          workspace_id uuid,
          title text,
          created_at timestamptz default now()
        )
        """
    )
    op.execute(
        """
        create table messages (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid not null,
          conversation_id uuid references conversations(id),
          role text not null,
          content text,
          tokens int,
          citations jsonb default '[]',
          created_at timestamptz default now()
        )
        """
    )
    op.execute(
        """
        create table usage_records (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid not null,
          channel_id uuid,
          model_id uuid,
          agent_id uuid,
          user_id uuid,
          prompt_tokens int,
          completion_tokens int,
          latency_ms int,
          cost numeric(12,6),
          cache_hit bool default false,
          created_at timestamptz default now()
        )
        """
    )
    op.execute("create index ix_usage_records_tenant_id_created_at on usage_records (tenant_id, created_at)")

    op.execute(
        """
        create table workspaces (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid not null,
          name text not null,
          layout jsonb default '{}',
          created_by uuid,
          created_at timestamptz default now()
        )
        """
    )
    op.execute(
        """
        create table workspace_resources (
          id uuid primary key default gen_random_uuid(),
          workspace_id uuid references workspaces(id),
          resource_type text,
          resource_id uuid
        )
        """
    )
    op.execute(
        """
        create table triggers (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid not null,
          workspace_id uuid,
          type text,
          config jsonb,
          status text default 'active'
        )
        """
    )
    op.execute(
        """
        create table run_traces (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid not null,
          conversation_id uuid,
          agent_id uuid,
          parent_id uuid,
          span_type text,
          name text,
          status text,
          input jsonb,
          output jsonb,
          tokens int,
          latency_ms int,
          created_at timestamptz default now()
        )
        """
    )
    op.execute("create index ix_run_traces_conversation_id on run_traces (conversation_id)")
    op.execute(
        """
        create table audit_logs (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid not null,
          user_id uuid,
          action text,
          resource_type text,
          resource_id uuid,
          ip text,
          detail jsonb,
          created_at timestamptz default now()
        )
        """
    )

    op.execute(
        """
        create table eval_cases (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid not null,
          scene text,
          input text,
          expected text,
          assert_type text,
          threshold numeric
        )
        """
    )
    op.execute(
        """
        create table eval_runs (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid not null,
          agent_id uuid,
          case_id uuid,
          score numeric,
          passed bool,
          detail jsonb,
          created_at timestamptz default now()
        )
        """
    )
    op.execute(
        """
        create table experiences (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid not null,
          agent_id uuid,
          scene text,
          content text,
          embedding vector(1536),
          meta jsonb,
          created_at timestamptz default now()
        )
        """
    )
    op.execute("create index ix_experiences_embedding on experiences using hnsw (embedding vector_cosine_ops)")

    op.execute(
        """
        create table experiments (
          id uuid primary key default gen_random_uuid(),
          tenant_id uuid not null,
          name text,
          type text,
          config jsonb,
          metrics jsonb,
          status text default 'draft'
        )
        """
    )


def downgrade() -> None:
    op.execute("drop table if exists experiments")
    op.execute("drop table if exists experiences")
    op.execute("drop table if exists eval_runs")
    op.execute("drop table if exists eval_cases")
    op.execute("drop table if exists audit_logs")
    op.execute("drop table if exists run_traces")
    op.execute("drop table if exists triggers")
    op.execute("drop table if exists workspace_resources")
    op.execute("drop table if exists workspaces")
    op.execute("drop table if exists usage_records")
    op.execute("drop table if exists messages")
    op.execute("drop table if exists conversations")
    op.execute("drop table if exists api_keys")
    op.execute("drop table if exists model_channels")
    op.execute("drop table if exists models")
    op.execute("drop table if exists agent_kbs")
    op.execute("drop table if exists agent_tools")
    op.execute("drop table if exists tools")
    op.execute("drop table if exists agents")
    op.execute("drop table if exists agent_templates")
    op.execute("drop table if exists chunks")
    op.execute("drop table if exists documents")
    op.execute("drop table if exists knowledge_bases")
    op.execute("drop table if exists role_permissions")
    op.execute("drop table if exists user_roles")
    op.execute("drop table if exists permissions")
    op.execute("drop table if exists roles")
    op.execute("drop table if exists users")
    op.execute("drop table if exists tenants")
    op.execute("drop extension if exists vector")
    op.execute("drop extension if exists pgcrypto")
