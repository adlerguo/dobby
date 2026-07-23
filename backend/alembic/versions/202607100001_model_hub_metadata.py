"""add model hub metadata fields

Revision ID: 202607100001
Revises: 202607080001
Create Date: 2026-07-10 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607100001"
down_revision: str | None = "202607080001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("models", sa.Column("display_name", sa.Text(), nullable=True))
    op.add_column("models", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "models",
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=True
        ),
    )
    op.add_column(
        "models",
        sa.Column(
            "provider_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=True,
        ),
    )
    op.add_column(
        "models",
        sa.Column(
            "import_source",
            sa.Text(),
            server_default=sa.text("'external'"),
            nullable=True,
        ),
    )
    op.add_column("models", sa.Column("model_icon_path", sa.Text(), nullable=True))
    op.add_column("models", sa.Column("publish_date", sa.Text(), nullable=True))
    op.add_column(
        "models",
        sa.Column(
            "scope_type", sa.Text(), server_default=sa.text("'tenant'"), nullable=True
        ),
    )
    op.add_column(
        "models",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )
    op.add_column(
        "models",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("models", "updated_at")
    op.drop_column("models", "created_at")
    op.drop_column("models", "scope_type")
    op.drop_column("models", "publish_date")
    op.drop_column("models", "model_icon_path")
    op.drop_column("models", "import_source")
    op.drop_column("models", "provider_config")
    op.drop_column("models", "is_active")
    op.drop_column("models", "description")
    op.drop_column("models", "display_name")
