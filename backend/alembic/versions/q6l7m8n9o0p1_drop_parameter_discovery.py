"""Drop Phase 6.4 active parameter discovery (feature removed).

Removes everything the parameter-discovery feature added:
  * the ``parameters`` and ``parameter_sources`` tables (+ indexes),
  * the aggregate ``parameter_count`` columns added to ``hosts`` and
    ``subdomains`` (the ``url``/``endpoint`` parameter_count columns are NOT
    touched — those count query-string params and are core URL data),
  * the Phase 6.4 metric columns on ``scan_runs``,
  * ``PARAMETER_DISCOVERY`` from the ``scan_runs`` scan_type check constraint.

Downgrade recreates the tables/columns empty so the schema round-trips, but the
data is gone — this is a destructive removal by design.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "q6l7m8n9o0p1"
down_revision = "p5k6l7m8n9o0"
branch_labels = None
depends_on = None


_SCAN_TYPES_WITHOUT_PARAM = (
    "'SUBDOMAIN', 'DNS', 'HTTP', 'PORT', 'URL', 'JS', "
    "'CONTENT_DISCOVERY', 'JS_ENDPOINT', 'JS_SECRET', 'TECHNOLOGY', 'SCREENSHOT'"
)
_SCAN_TYPES_WITH_PARAM = (
    "'SUBDOMAIN', 'DNS', 'HTTP', 'PORT', 'URL', 'JS', "
    "'CONTENT_DISCOVERY', 'JS_ENDPOINT', 'JS_SECRET', "
    "'PARAMETER_DISCOVERY', 'TECHNOLOGY', 'SCREENSHOT'"
)


def _bind():
    return op.get_bind()


def _table_exists(name: str) -> bool:
    return sa.inspect(_bind()).has_table(name)


def _column_exists(table: str, column: str) -> bool:
    insp = sa.inspect(_bind())
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def _constraint_exists(name: str) -> bool:
    insp = sa.inspect(_bind())
    if not insp.has_table("scan_runs"):
        return False
    return any(c["name"] == name for c in insp.get_check_constraints("scan_runs"))


def upgrade() -> None:
    # Purge any leftover PARAMETER_DISCOVERY scan_run rows — the feature is gone,
    # so these are orphans, and they'd otherwise violate the narrowed constraint.
    op.execute("DELETE FROM scan_runs WHERE scan_type = 'PARAMETER_DISCOVERY'")

    # Narrow the scan_type check constraint (remove PARAMETER_DISCOVERY).
    if _constraint_exists("ck_scan_runs_scan_type"):
        op.drop_constraint("ck_scan_runs_scan_type", "scan_runs", type_="check")
    op.create_check_constraint(
        "ck_scan_runs_scan_type", "scan_runs",
        f"scan_type IN ({_SCAN_TYPES_WITHOUT_PARAM})",
    )

    # Drop the Phase 6.4 scan-run metric columns.
    for name in (
        "arjun_count", "paramspider_count", "assets_scanned_count",
        "total_parameters_count", "new_parameters_count",
    ):
        if _column_exists("scan_runs", name):
            op.drop_column("scan_runs", name)

    # Drop the aggregate parameter_count columns on hosts/subdomains only.
    for table in ("subdomains", "hosts"):
        if _column_exists(table, "parameter_count"):
            op.drop_column(table, "parameter_count")

    # Drop the parameter tables (parameter_sources first — it FKs parameters).
    if _table_exists("parameter_sources"):
        op.drop_table("parameter_sources")
    if _table_exists("parameters"):
        op.drop_table("parameters")


def downgrade() -> None:
    # Recreate parameters.
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

    # Recreate parameter_sources.
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

    # Recreate the aggregate parameter_count columns.
    for table in ("hosts", "subdomains"):
        if not _column_exists(table, "parameter_count"):
            op.add_column(table, sa.Column(
                "parameter_count", sa.Integer(), nullable=False, server_default="0"))

    # Recreate the scan-run metric columns.
    for name in (
        "arjun_count", "paramspider_count", "assets_scanned_count",
        "total_parameters_count", "new_parameters_count",
    ):
        if not _column_exists("scan_runs", name):
            op.add_column("scan_runs", sa.Column(
                name, sa.Integer(), nullable=False, server_default="0"))

    # Re-widen the scan_type check constraint.
    if _constraint_exists("ck_scan_runs_scan_type"):
        op.drop_constraint("ck_scan_runs_scan_type", "scan_runs", type_="check")
    op.create_check_constraint(
        "ck_scan_runs_scan_type", "scan_runs",
        f"scan_type IN ({_SCAN_TYPES_WITH_PARAM})",
    )
