"""refactor schema for program settings, assets, and scan runs

Revision ID: b1f2c3d4e5f6
Revises: fe5fe224c706
Create Date: 2026-06-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b1f2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "fe5fe224c706"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("programs", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("programs", sa.Column("created_by", sa.Text(), nullable=True))

    op.add_column(
        "scopes",
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("50")),
    )
    op.add_column(
        "scopes",
        sa.Column("last_scan_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scopes",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_scopes_program_id", "scopes", ["program_id"])

    op.add_column(
        "scan_runs",
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "scan_runs",
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "scan_runs",
        sa.Column("scan_type", sa.String(length=128), nullable=False, server_default=sa.text("'unknown'")),
    )
    op.add_column(
        "scan_runs",
        sa.Column("records_found", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "scan_runs",
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_scan_runs_program_id", "scan_runs", ["program_id"])
    op.create_index("ix_scan_runs_scope_id", "scan_runs", ["scope_id"])
    op.create_index("ix_scan_runs_scan_type", "scan_runs", ["scan_type"])
    op.create_index("ix_scan_runs_status", "scan_runs", ["status"])
    op.create_foreign_key(
        "fk_scan_runs_program_id_programs",
        "scan_runs",
        "programs",
        ["program_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_scan_runs_scope_id_scopes",
        "scan_runs",
        "scopes",
        ["scope_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_table(
        "program_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subdomain_scan_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("url_scan_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("js_scan_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("technology_scan_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("screenshot_scan_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notification_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("scan_frequency", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("program_id"),
    )
    op.create_index("ix_program_settings_program_id", "program_settings", ["program_id"])

    op.create_table(
        "assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_type", sa.String(length=128), nullable=False),
        sa.Column("asset_value", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scope_id"], ["scopes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assets_program_id", "assets", ["program_id"])
    op.create_index("ix_assets_scope_id", "assets", ["scope_id"])
    op.create_index("ix_assets_asset_type", "assets", ["asset_type"])
    op.create_index("ix_assets_asset_value", "assets", ["asset_value"])
    op.create_index("ix_assets_status", "assets", ["status"])


def downgrade() -> None:
    op.drop_index("ix_assets_status", table_name="assets")
    op.drop_index("ix_assets_asset_value", table_name="assets")
    op.drop_index("ix_assets_asset_type", table_name="assets")
    op.drop_index("ix_assets_scope_id", table_name="assets")
    op.drop_index("ix_assets_program_id", table_name="assets")
    op.drop_table("assets")
    op.drop_index("ix_program_settings_program_id", table_name="program_settings")
    op.drop_table("program_settings")
    op.drop_constraint("fk_scan_runs_scope_id_scopes", "scan_runs", type_="foreignkey")
    op.drop_constraint("fk_scan_runs_program_id_programs", "scan_runs", type_="foreignkey")
    op.drop_index("ix_scan_runs_status", table_name="scan_runs")
    op.drop_index("ix_scan_runs_scan_type", table_name="scan_runs")
    op.drop_index("ix_scan_runs_scope_id", table_name="scan_runs")
    op.drop_index("ix_scan_runs_program_id", table_name="scan_runs")
    op.drop_column("scan_runs", "error_message")
    op.drop_column("scan_runs", "records_found")
    op.drop_column("scan_runs", "scan_type")
    op.drop_column("scan_runs", "scope_id")
    op.drop_column("scan_runs", "program_id")
    op.drop_index("ix_scopes_program_id", table_name="scopes")
    op.drop_column("scopes", "updated_at")
    op.drop_column("scopes", "last_scan_at")
    op.drop_column("scopes", "priority")
    op.drop_column("programs", "created_by")
    op.drop_column("programs", "description")
