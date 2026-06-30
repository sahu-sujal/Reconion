"""Drop resolved_count from scan_runs and resolved column + index from subdomains.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-06-10

Changes:
    - Drop scan_runs.resolved_count
    - Drop index ix_subdomains_resolved_true on subdomains
    - Drop subdomains.resolved column
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("scan_runs", "resolved_count")

    op.execute("DROP INDEX IF EXISTS ix_subdomains_resolved_true")
    op.execute("DROP INDEX IF EXISTS ix_subdomains_resolved")
    op.drop_column("subdomains", "resolved")


def downgrade() -> None:
    op.add_column(
        "subdomains",
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.execute(
        "CREATE INDEX ix_subdomains_resolved_true "
        "ON subdomains (scope_id, subdomain) WHERE resolved = true"
    )
    op.add_column(
        "scan_runs",
        sa.Column("resolved_count", sa.Integer(), nullable=False, server_default="0"),
    )
