"""Add subjs_count metric column to scan_runs (Subjs JS discovery).

Subjs is added as a JavaScript-discovery tool in Phase 5. Its per-scan raw count
is recorded on scan_runs alongside gau/katana/hakrawler for the Discord
breakdown. No js_files schema change is needed — Subjs uses the existing table.

Revision ID: l1g2h3i4j5k6
Revises: k0f1g2h3i4j5
Create Date: 2026-07-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "l1g2h3i4j5k6"
down_revision = "k0f1g2h3i4j5"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    result = op.get_bind().execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": column},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    if not _column_exists("scan_runs", "subjs_count"):
        op.add_column(
            "scan_runs",
            sa.Column("subjs_count", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    if _column_exists("scan_runs", "subjs_count"):
        op.drop_column("scan_runs", "subjs_count")
