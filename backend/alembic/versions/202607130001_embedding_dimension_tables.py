"""Add configurable embedding dimensions and dimension chunk tables."""

from alembic import op


revision = "202607130001"
down_revision = "202607100003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "alter table knowledge_bases add column if not exists embedding_dim int not null default 1536"
    )
    for dim in (1024, 3072):
        table = f"chunks_{dim}"
        op.execute(
            f"""
            create table if not exists {table} (
              id uuid primary key default gen_random_uuid(),
              tenant_id uuid not null,
              kb_id uuid not null references knowledge_bases(id),
              doc_id uuid not null references documents(id),
              seq int,
              content text not null,
              tokens int,
              meta jsonb default '{{}}',
              embedding vector({dim}),
              created_at timestamptz default now()
            )
            """
        )
        if dim <= 2000:
            op.execute(
                f"create index if not exists ix_{table}_embedding on {table} using hnsw (embedding vector_cosine_ops)"
            )
        op.execute(f"create index if not exists ix_{table}_kb_id on {table} (kb_id)")
        op.execute(
            f"create index if not exists {table}_content_fts on {table} using gin (to_tsvector('simple', content))"
        )


def downgrade() -> None:
    op.execute("drop table if exists chunks_3072")
    op.execute("drop table if exists chunks_1024")
    op.execute("alter table knowledge_bases drop column if exists embedding_dim")
