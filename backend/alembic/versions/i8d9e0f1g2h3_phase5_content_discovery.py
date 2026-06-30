"""Phase 5 — Content Discovery models.

Rebuilds the ``urls`` table with the rich Phase-5 schema and adds:
  - urls            (rebuilt: normalized_url, scheme/host/path/query/…, counters)
  - url_sources     (per-tool attribution for URLs)
  - js_files        (discovered JavaScript assets)
  - js_file_sources (per-tool attribution for JS files)

Alters:
  - hosts:     add url_count, js_count maintained counters
  - scan_runs: add gau/waybackurls/katana/hakrawler/total_urls/new_urls/
               total_js/new_js metric columns, widen scan_type check constraint

The legacy ``urls`` table (Phase-3 stub: asset_id/url/source/status) carried no
production data, so it is dropped and recreated rather than migrated in place.

Revision ID: i8d9e0f1g2h3
Revises: h7c8d9e0f1g2
Create Date: 2026-06-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "i8d9e0f1g2h3"
down_revision = "h7c8d9e0f1g2"
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
    # hosts — maintained counters
    # ------------------------------------------------------------------
    if not _column_exists("hosts", "url_count"):
        op.add_column("hosts", sa.Column("url_count", sa.Integer(), nullable=False, server_default="0"))
    if not _column_exists("hosts", "js_count"):
        op.add_column("hosts", sa.Column("js_count", sa.Integer(), nullable=False, server_default="0"))

    # ------------------------------------------------------------------
    # scan_runs — content discovery metric columns
    # ------------------------------------------------------------------
    for col in (
        "gau_count", "waybackurls_count", "katana_count", "hakrawler_count",
        "total_urls_count", "new_urls_count", "total_js_count", "new_js_count",
    ):
        if not _column_exists("scan_runs", col):
            op.add_column(
                "scan_runs",
                sa.Column(col, sa.Integer(), nullable=False, server_default="0"),
            )

    # Widen scan_type check constraint to include CONTENT_DISCOVERY
    if _constraint_exists("ck_scan_runs_scan_type"):
        op.drop_constraint("ck_scan_runs_scan_type", "scan_runs", type_="check")
    op.create_check_constraint(
        "ck_scan_runs_scan_type",
        "scan_runs",
        "scan_type IN ('SUBDOMAIN', 'DNS', 'HTTP', 'PORT', 'URL', 'JS', "
        "'CONTENT_DISCOVERY', 'TECHNOLOGY', 'SCREENSHOT')",
    )

    # ------------------------------------------------------------------
    # Drop the legacy urls table (stub) and its dependents, then rebuild
    # ------------------------------------------------------------------
    if _table_exists("url_sources"):
        op.drop_table("url_sources")
    if _table_exists("urls"):
        op.drop_table("urls")

    op.create_table(
        "urls",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("scheme", sa.String(16), nullable=True),
        sa.Column("host", sa.String(255), nullable=True),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("query", sa.Text(), nullable=True),
        sa.Column("fragment", sa.Text(), nullable=True),
        sa.Column("extension", sa.String(32), nullable=True),
        sa.Column("directory", sa.Text(), nullable=True),
        sa.Column("filename", sa.String(512), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parameter_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("has_parameters", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("status", sa.String(64), nullable=True),
        sa.Column("source", sa.String(255), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scope_id"], ["scopes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["host_id"], ["hosts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope_id", "normalized_url", name="uq_urls_scope_normalized"),
    )
    for idx, cols in [
        ("ix_urls_program_id", ["program_id"]),
        ("ix_urls_scope_id", ["scope_id"]),
        ("ix_urls_host_id", ["host_id"]),
        ("ix_urls_normalized_url", ["normalized_url"]),
        ("ix_urls_host", ["host"]),
        ("ix_urls_extension", ["extension"]),
        ("ix_urls_has_parameters", ["has_parameters"]),
        ("ix_urls_status", ["status"]),
        ("ix_urls_source", ["source"]),
        ("ix_urls_program_id_normalized", ["program_id", "normalized_url"]),
        ("ix_urls_host_id_normalized", ["host_id", "normalized_url"]),
    ]:
        if not _index_exists(idx):
            op.create_index(idx, "urls", cols)

    # ------------------------------------------------------------------
    # url_sources
    # ------------------------------------------------------------------
    op.create_table(
        "url_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["url_id"], ["urls.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url_id", "tool_name", name="uq_url_sources_url_tool"),
    )
    for idx, col in [("ix_url_sources_url_id", "url_id"), ("ix_url_sources_tool_name", "tool_name")]:
        if not _index_exists(idx):
            op.create_index(idx, "url_sources", [col])

    # ------------------------------------------------------------------
    # js_files
    # ------------------------------------------------------------------
    if not _table_exists("js_files"):
        op.create_table(
            "js_files",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("filename", sa.String(512), nullable=True),
            sa.Column("directory", sa.Text(), nullable=True),
            sa.Column("extension", sa.String(32), nullable=True),
            sa.Column("source", sa.String(255), nullable=True),
            sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["scope_id"], ["scopes.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["host_id"], ["hosts.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("scope_id", "url", name="uq_js_files_scope_url"),
        )
    for idx, cols in [
        ("ix_js_files_program_id", ["program_id"]),
        ("ix_js_files_scope_id", ["scope_id"]),
        ("ix_js_files_host_id", ["host_id"]),
        ("ix_js_files_source", ["source"]),
        ("ix_js_files_program_id_url", ["program_id", "url"]),
        ("ix_js_files_host_id_url", ["host_id", "url"]),
    ]:
        if not _index_exists(idx):
            op.create_index(idx, "js_files", cols)

    # ------------------------------------------------------------------
    # js_file_sources
    # ------------------------------------------------------------------
    if not _table_exists("js_file_sources"):
        op.create_table(
            "js_file_sources",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("js_file_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tool_name", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["js_file_id"], ["js_files.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("js_file_id", "tool_name", name="uq_js_file_sources_js_tool"),
        )
    for idx, col in [
        ("ix_js_file_sources_js_file_id", "js_file_id"),
        ("ix_js_file_sources_tool_name", "tool_name"),
    ]:
        if not _index_exists(idx):
            op.create_index(idx, "js_file_sources", [col])


def downgrade() -> None:
    if _table_exists("js_file_sources"):
        op.drop_table("js_file_sources")
    if _table_exists("js_files"):
        op.drop_table("js_files")
    if _table_exists("url_sources"):
        op.drop_table("url_sources")
    if _table_exists("urls"):
        op.drop_table("urls")

    # Recreate the legacy urls stub so the prior revision is consistent
    op.create_table(
        "urls",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("source", sa.String(255), nullable=True),
        sa.Column("status", sa.String(64), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scope_id"], ["scopes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    if _constraint_exists("ck_scan_runs_scan_type"):
        op.drop_constraint("ck_scan_runs_scan_type", "scan_runs", type_="check")
    op.create_check_constraint(
        "ck_scan_runs_scan_type",
        "scan_runs",
        "scan_type IN ('SUBDOMAIN', 'DNS', 'HTTP', 'PORT', 'URL', 'JS', "
        "'TECHNOLOGY', 'SCREENSHOT')",
    )
    for col in (
        "new_js_count", "total_js_count", "new_urls_count", "total_urls_count",
        "hakrawler_count", "katana_count", "waybackurls_count", "gau_count",
    ):
        if _column_exists("scan_runs", col):
            op.drop_column("scan_runs", col)

    for col in ("js_count", "url_count"):
        if _column_exists("hosts", col):
            op.drop_column("hosts", col)
