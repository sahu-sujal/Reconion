"""create tool_executions table

Revision ID: 6a7b8c9d0e1f
Revises: 5f1e2d3c4b6a
Create Date: 2026-06-07 23:50:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "6a7b8c9d0e1f"
down_revision = "5f1e2d3c4b6a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_executions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scan_run_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "RUNNING",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                name="tool_execution_status",
                native_enum=False,
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("output_path", sa.String(length=512), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["scan_run_id"], ["scan_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tool_executions_scan_run_id", "tool_executions", ["scan_run_id"])
    op.create_index("ix_tool_executions_tool_name", "tool_executions", ["tool_name"])
    op.create_index("ix_tool_executions_status", "tool_executions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_tool_executions_status", table_name="tool_executions")
    op.drop_index("ix_tool_executions_tool_name", table_name="tool_executions")
    op.drop_index("ix_tool_executions_scan_run_id", table_name="tool_executions")
    op.drop_table("tool_executions")
