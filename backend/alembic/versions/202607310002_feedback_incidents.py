"""add feedback and conversation incidents

Revision ID: 202607310002
Revises: 202607310001
Create Date: 2026-07-31 00:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202607310002"
down_revision: str | None = "202607310001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        create table if not exists message_feedback (
          id uuid primary key,
          tenant_id uuid not null,
          message_id uuid not null references messages(id),
          conversation_id uuid null references conversations(id),
          agent_id uuid null references agents(id),
          trace_id uuid null references run_traces(id),
          rating text not null,
          reason text null,
          comment text null,
          citations jsonb not null default '[]'::jsonb,
          meta jsonb not null default '{}'::jsonb,
          created_by uuid null references users(id),
          created_at timestamptz not null default now()
        )
        """
    )
    op.execute(
        """
        create table if not exists conversation_incidents (
          id uuid primary key,
          tenant_id uuid not null,
          conversation_id uuid null references conversations(id),
          message_id uuid null references messages(id),
          agent_id uuid null references agents(id),
          trace_id uuid null references run_traces(id),
          incident_type text not null,
          severity text not null,
          status text not null default 'open',
          title text not null,
          detail jsonb not null default '{}'::jsonb,
          resolution_note text null,
          created_by uuid null references users(id),
          resolved_by uuid null references users(id),
          created_at timestamptz not null default now(),
          resolved_at timestamptz null
        )
        """
    )
    op.execute(
        "create index if not exists ix_message_feedback_tenant_message on message_feedback (tenant_id, message_id)"
    )
    op.execute(
        "create index if not exists ix_message_feedback_tenant_agent_created on message_feedback (tenant_id, agent_id, created_at desc)"
    )
    op.execute(
        "create index if not exists ix_message_feedback_tenant_rating_created on message_feedback (tenant_id, rating, created_at desc)"
    )
    op.execute(
        "create index if not exists ix_incidents_tenant_status_created on conversation_incidents (tenant_id, status, created_at desc)"
    )
    op.execute(
        "create index if not exists ix_incidents_tenant_type_created on conversation_incidents (tenant_id, incident_type, created_at desc)"
    )
    op.execute(
        "create index if not exists ix_incidents_tenant_agent_created on conversation_incidents (tenant_id, agent_id, created_at desc)"
    )
    op.execute(
        """
        create unique index if not exists uq_incidents_tenant_trace_type
        on conversation_incidents (tenant_id, trace_id, incident_type)
        where trace_id is not null
        """
    )


def downgrade() -> None:
    op.execute("drop index if exists uq_incidents_tenant_trace_type")
    op.execute("drop index if exists ix_incidents_tenant_agent_created")
    op.execute("drop index if exists ix_incidents_tenant_type_created")
    op.execute("drop index if exists ix_incidents_tenant_status_created")
    op.execute("drop index if exists ix_message_feedback_tenant_rating_created")
    op.execute("drop index if exists ix_message_feedback_tenant_agent_created")
    op.execute("drop index if exists ix_message_feedback_tenant_message")
    op.execute("drop table if exists conversation_incidents")
    op.execute("drop table if exists message_feedback")
