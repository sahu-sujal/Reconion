"""Scan control (pause/resume/stop) — add resume_state checkpoint column.

Adds:
  - scan_runs.resume_state (JSONB, nullable) — worker-defined checkpoint for a
    paused scan (e.g. {"js_offset": 900}); NULL for scans that never paused.

The PAUSED scan status needs no schema change: scan_runs.status is stored as a
plain VARCHAR (SQLAlchemy Enum with native_enum=False, no DB check constraint),
so the new value is accepted as-is.

Revision ID: k0f1g2h3i4j5
Revises: j9e0f1g2h3i4
Create Date: 2026-07-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "k0f1g2h3i4j5"
down_revision = "j9e0f1g2h3i4"
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
    if not _column_exists("scan_runs", "resume_state"):
        op.add_column(
            "scan_runs",
            sa.Column("resume_state", postgresql.JSONB(), nullable=True),
        )


def downgrade() -> None:
    if _column_exists("scan_runs", "resume_state"):
        op.drop_column("scan_runs", "resume_state")
