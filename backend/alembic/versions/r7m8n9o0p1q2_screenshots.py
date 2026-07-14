"""Add screenshots table + host screenshot counters (gowitness screenshots).

Creates the ``screenshots`` table (one row per host+url capture) and adds the
maintained ``screenshot_count`` / ``screenshot_path`` columns to ``hosts``.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "r7m8n9o0p1q2"
down_revision = "q6l7m8n9o0p1"
branch_labels = None
depends_on = None


def _bind():
    return op.get_bind()


def _table_exists(name: str) -> bool:
    return sa.inspect(_bind()).has_table(name)


def _column_exists(table: str, column: str) -> bool:
    insp = sa.inspect(_bind())
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if not _column_exists("hosts", "screenshot_count"):
        op.add_column("hosts", sa.Column(
            "screenshot_count", sa.Integer(), nullable=False, server_default="0"))
    if not _column_exists("hosts", "screenshot_path"):
        op.add_column("hosts", sa.Column(
            "screenshot_path", sa.String(1024), nullable=True))

    if not _table_exists("screenshots"):
        op.create_table(
            "screenshots",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("program_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("programs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("scope_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("scopes.id", ondelete="CASCADE"), nullable=False),
            sa.Column("host_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("final_url", sa.Text(), nullable=True),
            sa.Column("title", sa.String(512), nullable=True),
            sa.Column("status_code", sa.Integer(), nullable=True),
            sa.Column("file_name", sa.String(512), nullable=True),
            sa.Column("file_path", sa.Text(), nullable=True),
            sa.Column("failed", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("failed_reason", sa.Text(), nullable=True),
            sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.UniqueConstraint("host_id", "url", name="uq_screenshots_host_url"),
        )
        op.create_index("ix_screenshots_host_id", "screenshots", ["host_id"])
        op.create_index("ix_screenshots_program_id", "screenshots", ["program_id"])
        op.create_index("ix_screenshots_scope_id", "screenshots", ["scope_id"])


def downgrade() -> None:
    if _table_exists("screenshots"):
        op.drop_table("screenshots")
    for name in ("screenshot_path", "screenshot_count"):
        if _column_exists("hosts", name):
            op.drop_column("hosts", name)
