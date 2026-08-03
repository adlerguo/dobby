"""create copilot task tables

Revision ID: 202608030001
Revises: 202607310003
Create Date: 2026-08-03 00:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202608030001"
down_revision: str | None = "202607310003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        create table if not exists copilot_tasks (
          id uuid primary key,
          tenant_id uuid not null,
          workspace_id uuid null,
          user_id uuid not null,
          conversation_id text null,
          title text not null,
          user_goal text not null,
          plan_version integer not null default 1,
          status text not null default 'planned',
          current_step_id uuid null,
          progress_percent integer not null default 0,
          plan jsonb not null default '{}'::jsonb,
          warnings jsonb not null default '[]'::jsonb,
          result_summary text null,
          error_code text null,
          error_message text null,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          started_at timestamptz null,
          completed_at timestamptz null,
          cancelled_at timestamptz null,
          cancellation_reason text null
        )
        """
    )
    op.execute(
        """
        create table if not exists copilot_task_steps (
          id uuid primary key,
          tenant_id uuid not null,
          task_id uuid not null references copilot_tasks(id),
          step_order integer not null,
          client_step_id text null,
          title text not null,
          description text null,
          tool_name text not null,
          tool_arguments jsonb not null default '{}'::jsonb,
          dependencies jsonb not null default '[]'::jsonb,
          wait_condition jsonb null,
          risk_level text not null default 'L1',
          requires_confirmation boolean not null default false,
          status text not null default 'pending',
          retry_count integer not null default 0,
          max_retries integer not null default 2,
          idempotency_key text not null,
          output jsonb null,
          error_code text null,
          error_message text null,
          claimed_by text null,
          claimed_at timestamptz null,
          lease_expires_at timestamptz null,
          heartbeat_at timestamptz null,
          execution_attempt integer not null default 0,
          next_retry_at timestamptz null,
          next_check_at timestamptz null,
          check_interval_seconds integer not null default 5,
          timeout_at timestamptz null,
          last_observed_status text null,
          check_count integer not null default 0,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          started_at timestamptz null,
          completed_at timestamptz null
        )
        """
    )
    op.execute(
        """
        create table if not exists copilot_task_events (
          id uuid primary key,
          tenant_id uuid not null,
          workspace_id uuid null,
          task_id uuid not null references copilot_tasks(id),
          step_id uuid null references copilot_task_steps(id),
          event_id integer not null,
          event_type text not null,
          payload jsonb not null default '{}'::jsonb,
          created_at timestamptz not null default now()
        )
        """
    )
    op.execute(
        "create index if not exists ix_copilot_tasks_tenant_user_status on copilot_tasks (tenant_id, user_id, status)"
    )
    op.execute(
        "create index if not exists ix_copilot_tasks_workspace_status on copilot_tasks (tenant_id, workspace_id, status)"
    )
    op.execute(
        "create index if not exists ix_copilot_task_steps_task_order on copilot_task_steps (task_id, step_order)"
    )
    op.execute(
        "create index if not exists ix_copilot_task_steps_status on copilot_task_steps (tenant_id, status)"
    )
    op.execute(
        "create index if not exists ix_copilot_task_steps_lease on copilot_task_steps (tenant_id, status, lease_expires_at)"
    )
    op.execute(
        "create index if not exists ix_copilot_task_steps_wait on copilot_task_steps (tenant_id, status, next_check_at)"
    )
    op.execute(
        "create unique index if not exists uq_copilot_task_steps_task_idempotency on copilot_task_steps (task_id, idempotency_key)"
    )
    op.execute(
        "create unique index if not exists uq_copilot_task_events_task_event on copilot_task_events (task_id, event_id)"
    )
    op.execute(
        "create index if not exists ix_copilot_task_events_task_event on copilot_task_events (task_id, event_id)"
    )
    op.execute(
        "create index if not exists ix_copilot_task_events_tenant_task_created on copilot_task_events (tenant_id, task_id, created_at)"
    )


def downgrade() -> None:
    op.execute("drop table if exists copilot_task_events")
    op.execute("drop table if exists copilot_task_steps")
    op.execute("drop table if exists copilot_tasks")
