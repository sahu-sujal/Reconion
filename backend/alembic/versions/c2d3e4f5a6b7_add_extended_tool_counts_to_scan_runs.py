"""Add per-tool count columns for knockpy, dnsgen, chaos, crtsh, findomain to scan_runs.

Revision ID: c2d3e4f5a6b7
Revises: 9d0e1f2a3b4c
Create Date: 2026-06-09

Changes:
    - Add knockpy_count  INTEGER NOT NULL DEFAULT 0
    - Add dnsgen_count   INTEGER NOT NULL DEFAULT 0
    - Add chaos_count    INTEGER NOT NULL DEFAULT 0
    - Add crtsh_count    INTEGER NOT NULL DEFAULT 0
    - Add findomain_count INTEGER NOT NULL DEFAULT 0
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c2d3e4f5a6b7"
down_revision = ("9d0e1f2a3b4c", "a0b1c2d3e4f5")
branch_labels = None
depends_on = None

_NEW_COLUMNS = [
    "knockpy_count",
    "dnsgen_count",
    "chaos_count",
    "crtsh_count",
    "findomain_count",
]


def upgrade() -> None:
    for col in _NEW_COLUMNS:
        op.add_column(
            "scan_runs",
            sa.Column(col, sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    for col in reversed(_NEW_COLUMNS):
        op.drop_column("scan_runs", col)
