"""Phase 6.4 — Active Parameter Discovery: parameters + parameter_sources.

Creates the centralized Parameter Inventory:

    parameters          one row per (scope, asset, parameter_name); tool-agnostic
    parameter_sources   per-tool attribution (Arjun / ParamSpider / future tools)

Adds the maintained ``parameter_count`` counter to hosts + subdomains (never
COUNT()-ed per request). Per-asset parameter counts reuse the existing
``parameter_count`` columns already present on urls + endpoints (Phase 6.3).

Revision ID: o4j5k6l7m8n9
Revises: n3i4j5k6l7m8
Create Date: 2026-07-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "o4j5k6l7m8n9"
down_revision = "n3i4j5k6l7m8"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    return op.get_bind().execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns WHERE table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": column},
    ).fetchone() is not None


def _table_exists(table: str) -> bool:
    return op.get_bind().execute(
        sa.text("SELECT to_regclass(:t)"), {"t": table}
    ).scalar() is not None


def upgrade() -> None:
    # ---- parameters ------------------------------------------------------- #
    if not _table_exists("parameters"):
        op.create_table(
            "parameters",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("program_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("programs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("scope_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("scopes.id", ondelete="CASCADE"), nullable=False),
            sa.Column("host_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("hosts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("asset_type", sa.String(16), nullable=False),
            sa.Column("asset_url", sa.Text(), nullable=False),
            sa.Column("host", sa.String(255), nullable=True),
            sa.Column("parameter_name", sa.String(256), nullable=False),
            sa.Column("parameter_type", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("parameter_source", sa.String(32), nullable=False, server_default="ACTIVE"),
            sa.Column("discovery_tools", postgresql.JSONB(), nullable=False, server_default="[]"),
            sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.UniqueConstraint("scope_id", "asset_id", "parameter_name",
                                name="uq_parameters_scope_asset_name"),
        )
        op.create_index("ix_parameters_program_id", "parameters", ["program_id"])
        op.create_index("ix_parameters_scope_id", "parameters", ["scope_id"])
        op.create_index("ix_parameters_host_id", "parameters", ["host_id"])
        op.create_index("ix_parameters_host", "parameters", ["host"])
        op.create_index("ix_parameters_parameter_name", "parameters", ["parameter_name"])
        op.create_index("ix_parameters_program_id_name", "parameters", ["program_id", "parameter_name"])
        op.create_index("ix_parameters_scope_id_name", "parameters", ["scope_id", "parameter_name"])
        op.create_index("ix_parameters_host_id_name", "parameters", ["host_id", "parameter_name"])
        op.create_index("ix_parameters_asset_id", "parameters", ["asset_id"])
        op.create_index("ix_parameters_parameter_type", "parameters", ["parameter_type"])
        op.create_index(
            "ix_parameters_discovery_tools_gin", "parameters", ["discovery_tools"],
            postgresql_using="gin",
        )

    # ---- parameter_sources ------------------------------------------------ #
    if not _table_exists("parameter_sources"):
        op.create_table(
            "parameter_sources",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("parameter_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("parameters.id", ondelete="CASCADE"), nullable=False),
            sa.Column("tool_name", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.UniqueConstraint("parameter_id", "tool_name",
                                name="uq_parameter_sources_param_tool"),
        )
        op.create_index("ix_parameter_sources_parameter_id", "parameter_sources", ["parameter_id"])
        op.create_index("ix_parameter_sources_tool_name", "parameter_sources", ["tool_name"])

    # ---- maintained parameter_count counter on hosts + subdomains --------- #
    if not _column_exists("hosts", "parameter_count"):
        op.add_column("hosts", sa.Column(
            "parameter_count", sa.Integer(), nullable=False, server_default="0"))
    if not _column_exists("subdomains", "parameter_count"):
        op.add_column("subdomains", sa.Column(
            "parameter_count", sa.Integer(), nullable=False, server_default="0"))

    # ---- Phase 6.4 scan-run metrics --------------------------------------- #
    for name in (
        "arjun_count", "paramspider_count", "assets_scanned_count",
        "total_parameters_count", "new_parameters_count",
    ):
        if not _column_exists("scan_runs", name):
            op.add_column("scan_runs", sa.Column(
                name, sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    for name in (
        "arjun_count", "paramspider_count", "assets_scanned_count",
        "total_parameters_count", "new_parameters_count",
    ):
        if _column_exists("scan_runs", name):
            op.drop_column("scan_runs", name)

    for col in ("subdomains", "hosts"):
        if _column_exists(col, "parameter_count"):
            op.drop_column(col, "parameter_count")

    if _table_exists("parameter_sources"):
        op.drop_table("parameter_sources")
    if _table_exists("parameters"):
        op.drop_table("parameters")
