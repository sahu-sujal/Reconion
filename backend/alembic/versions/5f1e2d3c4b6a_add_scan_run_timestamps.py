"""add timestamps to scan_runs

Revision ID: 5f1e2d3c4b6a
Revises: b1f2c3d4e5f6
Create Date: 2026-06-07 23:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "5f1e2d3c4b6a"
down_revision = "4a5b6c7d8e9f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scan_runs",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "scan_runs",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_column("scan_runs", "updated_at")
    op.drop_column("scan_runs", "created_at")
