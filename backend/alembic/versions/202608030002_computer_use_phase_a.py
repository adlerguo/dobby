"""create computer use phase a tables

Revision ID: 202608030002
Revises: 202608030001
Create Date: 2026-08-03 00:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202608030002"
down_revision: str | None = "202608030001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        create table if not exists computer_use_targets (
          id uuid primary key,
          tenant_id uuid not null,
          workspace_id uuid null,
          name text not null,
          description text null,
          allowed_domains jsonb not null default '[]'::jsonb,
          allowed_url_patterns jsonb not null default '[]'::jsonb,
          denied_url_patterns jsonb not null default '[]'::jsonb,
          allow_navigation boolean not null default true,
          allow_form_fill boolean not null default false,
          allow_submit boolean not null default false,
          allow_upload boolean not null default false,
          allow_download boolean not null default false,
          allow_login boolean not null default false,
          allow_persistent_session boolean not null default false,
          max_session_minutes integer not null default 15,
          max_actions integer not null default 20,
          enabled boolean not null default false,
          created_by uuid null,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        )
        """
    )
    op.execute(
        """
        create table if not exists computer_use_sessions (
          id uuid primary key,
          tenant_id uuid not null,
          workspace_id uuid null,
          user_id uuid not null,
          task_id uuid null references copilot_tasks(id),
          conversation_id text null,
          target_id uuid not null references computer_use_targets(id),
          status text not null default 'pending_consent',
          execution_mode text not null default 'read_only_browser',
          current_url text null,
          current_title text null,
          allowed_domains jsonb not null default '[]'::jsonb,
          user_goal text not null,
          approved_plan jsonb not null default '{}'::jsonb,
          risk_level text not null default 'L1',
          started_at timestamptz null,
          last_activity_at timestamptz null,
          expires_at timestamptz null,
          paused_at timestamptz null,
          completed_at timestamptz null,
          stopped_at timestamptz null,
          stop_reason text null,
          takeover_required boolean not null default false,
          browser_context_ref text null,
          worker_id text null,
          security_events jsonb not null default '[]'::jsonb,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        )
        """
    )
    op.execute(
        """
        create table if not exists computer_use_actions (
          id uuid primary key,
          tenant_id uuid not null,
          session_id uuid not null references computer_use_sessions(id),
          task_step_id uuid null references copilot_task_steps(id),
          sequence integer not null,
          action_type text not null,
          target_description text null,
          selector_strategy text null,
          selector_value text null,
          sanitized_input jsonb not null default '{}'::jsonb,
          before_url text null,
          after_url text null,
          before_screenshot_id text null,
          after_screenshot_id text null,
          status text not null default 'pending',
          risk_level text not null default 'L1',
          requires_confirmation boolean not null default false,
          confirmation_id text null,
          error_code text null,
          error_message text null,
          created_at timestamptz not null default now(),
          completed_at timestamptz null
        )
        """
    )
    op.execute(
        "create index if not exists ix_computer_use_targets_tenant_workspace on computer_use_targets (tenant_id, workspace_id)"
    )
    op.execute(
        "create index if not exists ix_computer_use_targets_tenant_enabled on computer_use_targets (tenant_id, enabled)"
    )
    op.execute(
        "create index if not exists ix_computer_use_sessions_tenant_user_status on computer_use_sessions (tenant_id, user_id, status)"
    )
    op.execute(
        "create index if not exists ix_computer_use_sessions_tenant_target on computer_use_sessions (tenant_id, target_id)"
    )
    op.execute(
        "create index if not exists ix_computer_use_sessions_workspace_status on computer_use_sessions (tenant_id, workspace_id, status)"
    )
    op.execute(
        "create index if not exists ix_computer_use_actions_session_sequence on computer_use_actions (session_id, sequence)"
    )
    op.execute(
        "create index if not exists ix_computer_use_actions_tenant_status on computer_use_actions (tenant_id, status)"
    )


def downgrade() -> None:
    op.execute("drop table if exists computer_use_actions")
    op.execute("drop table if exists computer_use_sessions")
    op.execute("drop table if exists computer_use_targets")
