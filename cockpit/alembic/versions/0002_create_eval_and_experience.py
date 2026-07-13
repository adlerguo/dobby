"""create eval and experience tables

Revision ID: 0002_create_eval_and_experience
Revises: 0001_create_cockpit_meta
Create Date: 2026-07-09 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002_create_eval_and_experience"
down_revision: str | None = "0001_create_cockpit_meta"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "eval_cases",
        sa.Column("target_type", sa.String(length=32), nullable=False, server_default="assistant"),
        sa.Column("target_id", sa.String(length=128), nullable=False),
        sa.Column("scene", sa.String(length=128), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("expected_answer", sa.Text(), nullable=True),
        sa.Column("expected_keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("scoring_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_cases_target", "eval_cases", ["target_type", "target_id"])

    op.create_table(
        "eval_runs",
        sa.Column("target_type", sa.String(length=32), nullable=False, server_default="assistant"),
        sa.Column("target_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("total_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("concurrency", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("run_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_runs_status", "eval_runs", ["status"])

    op.create_table(
        "eval_run_items",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("score", sa.Numeric(5, 2), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("first_frame_latency_ms", sa.Integer(), nullable=True),
        sa.Column("total_latency_ms", sa.Integer(), nullable=True),
        sa.Column("frame_count", sa.Integer(), nullable=True),
        sa.Column("conversation_id", sa.String(length=128), nullable=True),
        sa.Column("raw_response", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["eval_cases.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["eval_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_run_items_run", "eval_run_items", ["run_id"])

    op.create_table(
        "experiences",
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.String(length=128), nullable=True),
        sa.Column("scene", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_experiences_target", "experiences", ["target_type", "target_id"])
    op.create_index("ix_experiences_created_by", "experiences", ["created_by"])


def downgrade() -> None:
    op.drop_index("ix_experiences_created_by", table_name="experiences")
    op.drop_index("ix_experiences_target", table_name="experiences")
    op.drop_table("experiences")
    op.drop_index("ix_eval_run_items_run", table_name="eval_run_items")
    op.drop_table("eval_run_items")
    op.drop_index("ix_eval_runs_status", table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_index("ix_eval_cases_target", table_name="eval_cases")
    op.drop_table("eval_cases")
