"""add query performance indexes

Revision ID: 202607220001
Revises: 202607140001
Create Date: 2026-07-22 00:00:00.000000
"""

from alembic import op


revision = "202607220001"
down_revision = "202607140001"
branch_labels = None
depends_on = None


CHUNK_TABLES = ("chunks", "chunks_1024", "chunks_3072")


def upgrade() -> None:
    for table in CHUNK_TABLES:
        op.execute(
            f"create index if not exists ix_{table}_tenant_kb on {table} (tenant_id, kb_id)"
        )
        op.execute(
            f"create index if not exists ix_{table}_tenant_doc_seq on {table} (tenant_id, doc_id, seq)"
        )

    op.execute(
        "create index if not exists ix_audit_logs_tenant_created_desc on audit_logs (tenant_id, created_at desc)"
    )
    op.execute(
        "create index if not exists ix_audit_logs_tenant_action_created_desc "
        "on audit_logs (tenant_id, action, created_at desc)"
    )
    op.execute(
        "create index if not exists ix_documents_tenant_kb_created_desc "
        "on documents (tenant_id, kb_id, created_at desc)"
    )
    op.execute(
        "create index if not exists ix_conversations_tenant_agent_created_desc "
        "on conversations (tenant_id, agent_id, created_at desc)"
    )
    op.execute(
        "create index if not exists ix_messages_tenant_conversation_created "
        "on messages (tenant_id, conversation_id, created_at)"
    )
    op.execute(
        "create index if not exists ix_run_traces_tenant_created_desc on run_traces (tenant_id, created_at desc)"
    )
    op.execute(
        "create index if not exists ix_usage_records_tenant_agent_created_desc "
        "on usage_records (tenant_id, agent_id, created_at desc)"
    )


def downgrade() -> None:
    op.execute("drop index if exists ix_usage_records_tenant_agent_created_desc")
    op.execute("drop index if exists ix_run_traces_tenant_created_desc")
    op.execute("drop index if exists ix_messages_tenant_conversation_created")
    op.execute("drop index if exists ix_conversations_tenant_agent_created_desc")
    op.execute("drop index if exists ix_documents_tenant_kb_created_desc")
    op.execute("drop index if exists ix_audit_logs_tenant_action_created_desc")
    op.execute("drop index if exists ix_audit_logs_tenant_created_desc")

    for table in CHUNK_TABLES:
        op.execute(f"drop index if exists ix_{table}_tenant_doc_seq")
        op.execute(f"drop index if exists ix_{table}_tenant_kb")
