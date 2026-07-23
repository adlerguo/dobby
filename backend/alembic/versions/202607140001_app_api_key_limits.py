"""add app api key config

Revision ID: 202607140001
Revises: 202607130001
Create Date: 2026-07-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202607140001"
down_revision = "202607130001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_api_keys",
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("app_api_keys", "config")
