"""Phase 6.1 — JavaScript endpoint discovery.

Adds:
  - endpoints         (unified endpoint inventory; dedup on scope_id+normalized_url)
  - endpoint_sources  (per-tool attribution for endpoints)

Alters:
  - hosts:      add endpoint_count maintained counter
  - subdomains: add endpoint_count maintained counter
  - scan_runs:  add linkfinder/xnlinkfinder/jsluice + processed/failed +
                total/new endpoint metric columns; widen scan_type check
                constraint to include JS_ENDPOINT

Revision ID: j9e0f1g2h3i4
Revises: i8d9e0f1g2h3
Create Date: 2026-07-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "j9e0f1g2h3i4"
down_revision = "i8d9e0f1g2h3"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Introspection guards (idempotent — safe to re-run)
# ---------------------------------------------------------------------------

def _column_exists(table: str, column: str) -> bool:
    result = op.get_bind().execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": column},
    )
    return result.fetchone() is not None


def _table_exists(table: str) -> bool:
    result = op.get_bind().execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=:t"
        ),
        {"t": table},
    )
    return result.fetchone() is not None


def _index_exists(index: str) -> bool:
    result = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname=:i"),
        {"i": index},
    )
    return result.fetchone() is not None


def _constraint_exists(constraint: str) -> bool:
    result = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_constraint WHERE conname=:c"),
        {"c": constraint},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # hosts / subdomains — maintained endpoint counters
    # ------------------------------------------------------------------
    if not _column_exists("hosts", "endpoint_count"):
        op.add_column("hosts", sa.Column("endpoint_count", sa.Integer(), nullable=False, server_default="0"))
    if not _column_exists("subdomains", "endpoint_count"):
        op.add_column("subdomains", sa.Column("endpoint_count", sa.Integer(), nullable=False, server_default="0"))

    # ------------------------------------------------------------------
    # scan_runs — JS endpoint discovery metric columns
    # ------------------------------------------------------------------
    for col in (
        "linkfinder_count", "xnlinkfinder_count", "jsluice_count",
        "js_processed_count", "js_failed_count",
        "total_endpoints_count", "new_endpoints_count",
    ):
        if not _column_exists("scan_runs", col):
            op.add_column(
                "scan_runs",
                sa.Column(col, sa.Integer(), nullable=False, server_default="0"),
            )

    # Widen scan_type check constraint to include JS_ENDPOINT
    if _constraint_exists("ck_scan_runs_scan_type"):
        op.drop_constraint("ck_scan_runs_scan_type", "scan_runs", type_="check")
    op.create_check_constraint(
        "ck_scan_runs_scan_type",
        "scan_runs",
        "scan_type IN ('SUBDOMAIN', 'DNS', 'HTTP', 'PORT', 'URL', 'JS', "
        "'CONTENT_DISCOVERY', 'JS_ENDPOINT', 'TECHNOLOGY', 'SCREENSHOT')",
    )

    # ------------------------------------------------------------------
    # endpoints
    # ------------------------------------------------------------------
    if not _table_exists("endpoints"):
        op.create_table(
            "endpoints",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("js_file_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("absolute_url", sa.Text(), nullable=False),
            sa.Column("normalized_url", sa.Text(), nullable=False),
            sa.Column("scheme", sa.String(16), nullable=True),
            sa.Column("host", sa.String(255), nullable=True),
            sa.Column("path", sa.Text(), nullable=True),
            sa.Column("query", sa.Text(), nullable=True),
            sa.Column("fragment", sa.Text(), nullable=True),
            sa.Column("discovery_tools", postgresql.JSONB(), nullable=False, server_default="[]"),
            sa.Column("discovery_source", sa.String(32), nullable=False, server_default="JS_DISCOVERY"),
            sa.Column("source_js_file", sa.Text(), nullable=True),
            sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["scope_id"], ["scopes.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["host_id"], ["hosts.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["js_file_id"], ["js_files.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("scope_id", "normalized_url", name="uq_endpoints_scope_normalized"),
        )
    for idx, cols in [
        ("ix_endpoints_program_id", ["program_id"]),
        ("ix_endpoints_scope_id", ["scope_id"]),
        ("ix_endpoints_host_id", ["host_id"]),
        ("ix_endpoints_js_file_id", ["js_file_id"]),
        ("ix_endpoints_host", ["host"]),
        ("ix_endpoints_normalized_url", ["normalized_url"]),
        ("ix_endpoints_source_js_file", ["source_js_file"]),
        ("ix_endpoints_discovery_source", ["discovery_source"]),
        ("ix_endpoints_program_id_normalized", ["program_id", "normalized_url"]),
        ("ix_endpoints_scope_id_normalized", ["scope_id", "normalized_url"]),
        ("ix_endpoints_host_id_normalized", ["host_id", "normalized_url"]),
        ("ix_endpoints_js_file_id_created", ["js_file_id", "created_at"]),
    ]:
        if not _index_exists(idx):
            op.create_index(idx, "endpoints", cols)

    # GIN index for discovery_tools membership queries (?, @> operators).
    if not _index_exists("ix_endpoints_discovery_tools_gin"):
        op.create_index(
            "ix_endpoints_discovery_tools_gin",
            "endpoints",
            ["discovery_tools"],
            postgresql_using="gin",
        )

    # ------------------------------------------------------------------
    # endpoint_sources
    # ------------------------------------------------------------------
    if not _table_exists("endpoint_sources"):
        op.create_table(
            "endpoint_sources",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("endpoint_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tool_name", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["endpoint_id"], ["endpoints.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("endpoint_id", "tool_name", name="uq_endpoint_sources_endpoint_tool"),
        )
    for idx, col in [
        ("ix_endpoint_sources_endpoint_id", "endpoint_id"),
        ("ix_endpoint_sources_tool_name", "tool_name"),
    ]:
        if not _index_exists(idx):
            op.create_index(idx, "endpoint_sources", [col])


def downgrade() -> None:
    if _table_exists("endpoint_sources"):
        op.drop_table("endpoint_sources")
    if _table_exists("endpoints"):
        op.drop_table("endpoints")

    if _constraint_exists("ck_scan_runs_scan_type"):
        op.drop_constraint("ck_scan_runs_scan_type", "scan_runs", type_="check")
    op.create_check_constraint(
        "ck_scan_runs_scan_type",
        "scan_runs",
        "scan_type IN ('SUBDOMAIN', 'DNS', 'HTTP', 'PORT', 'URL', 'JS', "
        "'CONTENT_DISCOVERY', 'TECHNOLOGY', 'SCREENSHOT')",
    )

    for col in (
        "new_endpoints_count", "total_endpoints_count",
        "js_failed_count", "js_processed_count",
        "jsluice_count", "xnlinkfinder_count", "linkfinder_count",
    ):
        if _column_exists("scan_runs", col):
            op.drop_column("scan_runs", col)

    if _column_exists("subdomains", "endpoint_count"):
        op.drop_column("subdomains", "endpoint_count")
    if _column_exists("hosts", "endpoint_count"):
        op.drop_column("hosts", "endpoint_count")
