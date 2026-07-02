"""Phase 6.2 — JavaScript secret discovery.

Adds:
  - js_secrets         (secret inventory; dedup on scope_id+fingerprint)
  - js_secret_sources  (per-scanner attribution)

Alters:
  - hosts:      add secret_count maintained counter
  - subdomains: add secret_count maintained counter
  - scan_runs:  add secretfinder/mantra/nuclei_exposures + total/new secret
                metric columns; widen scan_type check constraint (JS_SECRET)

Revision ID: m2h3i4j5k6l7
Revises: l1g2h3i4j5k6
Create Date: 2026-07-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "m2h3i4j5k6l7"
down_revision = "l1g2h3i4j5k6"
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
        sa.text(
            "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=:t"
        ),
        {"t": table},
    ).fetchone() is not None


def _index_exists(index: str) -> bool:
    return op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname=:i"),
        {"i": index},
    ).fetchone() is not None


def _constraint_exists(constraint: str) -> bool:
    return op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_constraint WHERE conname=:c"),
        {"c": constraint},
    ).fetchone() is not None


_SCAN_TYPES_WITH_SECRET = (
    "'SUBDOMAIN', 'DNS', 'HTTP', 'PORT', 'URL', 'JS', 'CONTENT_DISCOVERY', "
    "'JS_ENDPOINT', 'JS_SECRET', 'TECHNOLOGY', 'SCREENSHOT'"
)
_SCAN_TYPES_WITHOUT_SECRET = (
    "'SUBDOMAIN', 'DNS', 'HTTP', 'PORT', 'URL', 'JS', 'CONTENT_DISCOVERY', "
    "'JS_ENDPOINT', 'TECHNOLOGY', 'SCREENSHOT'"
)


def upgrade() -> None:
    # counters
    if not _column_exists("hosts", "secret_count"):
        op.add_column("hosts", sa.Column("secret_count", sa.Integer(), nullable=False, server_default="0"))
    if not _column_exists("subdomains", "secret_count"):
        op.add_column("subdomains", sa.Column("secret_count", sa.Integer(), nullable=False, server_default="0"))

    # scan_runs metric columns
    for col in (
        "secretfinder_count", "mantra_count", "nuclei_exposures_count",
        "total_secrets_count", "new_secrets_count",
    ):
        if not _column_exists("scan_runs", col):
            op.add_column("scan_runs", sa.Column(col, sa.Integer(), nullable=False, server_default="0"))

    # widen scan_type check constraint
    if _constraint_exists("ck_scan_runs_scan_type"):
        op.drop_constraint("ck_scan_runs_scan_type", "scan_runs", type_="check")
    op.create_check_constraint(
        "ck_scan_runs_scan_type", "scan_runs",
        f"scan_type IN ({_SCAN_TYPES_WITH_SECRET})",
    )

    # js_secrets
    if not _table_exists("js_secrets"):
        op.create_table(
            "js_secrets",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("js_file_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("js_file_url", sa.Text(), nullable=True),
            sa.Column("host", sa.String(255), nullable=True),
            sa.Column("secret_type", sa.String(64), nullable=False),
            sa.Column("secret_value", sa.Text(), nullable=False),
            sa.Column("normalized_secret", sa.Text(), nullable=False),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column("confidence", sa.Integer(), nullable=False, server_default="50"),
            sa.Column("severity", sa.String(16), nullable=False, server_default="INFO"),
            sa.Column("discovery_tools", postgresql.JSONB(), nullable=False, server_default="[]"),
            sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["scope_id"], ["scopes.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["host_id"], ["hosts.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["js_file_id"], ["js_files.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("scope_id", "fingerprint", name="uq_js_secrets_scope_fingerprint"),
        )
    for idx, cols in [
        ("ix_js_secrets_program_id", ["program_id"]),
        ("ix_js_secrets_scope_id", ["scope_id"]),
        ("ix_js_secrets_host_id", ["host_id"]),
        ("ix_js_secrets_js_file_id", ["js_file_id"]),
        ("ix_js_secrets_host", ["host"]),
        ("ix_js_secrets_secret_type", ["secret_type"]),
        ("ix_js_secrets_severity", ["severity"]),
        ("ix_js_secrets_fingerprint", ["fingerprint"]),
        ("ix_js_secrets_js_file_url", ["js_file_url"]),
        ("ix_js_secrets_normalized_secret", ["normalized_secret"]),
        ("ix_js_secrets_program_id_severity", ["program_id", "severity"]),
        ("ix_js_secrets_scope_id_type", ["scope_id", "secret_type"]),
        ("ix_js_secrets_host_id_type", ["host_id", "secret_type"]),
    ]:
        if not _index_exists(idx):
            op.create_index(idx, "js_secrets", cols)
    if not _index_exists("ix_js_secrets_discovery_tools_gin"):
        op.create_index(
            "ix_js_secrets_discovery_tools_gin", "js_secrets",
            ["discovery_tools"], postgresql_using="gin",
        )

    # js_secret_sources
    if not _table_exists("js_secret_sources"):
        op.create_table(
            "js_secret_sources",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("secret_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tool_name", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["secret_id"], ["js_secrets.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("secret_id", "tool_name", name="uq_js_secret_sources_secret_tool"),
        )
    for idx, col in [
        ("ix_js_secret_sources_secret_id", "secret_id"),
        ("ix_js_secret_sources_tool_name", "tool_name"),
    ]:
        if not _index_exists(idx):
            op.create_index(idx, "js_secret_sources", [col])


def downgrade() -> None:
    if _table_exists("js_secret_sources"):
        op.drop_table("js_secret_sources")
    if _table_exists("js_secrets"):
        op.drop_table("js_secrets")

    if _constraint_exists("ck_scan_runs_scan_type"):
        op.drop_constraint("ck_scan_runs_scan_type", "scan_runs", type_="check")
    op.create_check_constraint(
        "ck_scan_runs_scan_type", "scan_runs",
        f"scan_type IN ({_SCAN_TYPES_WITHOUT_SECRET})",
    )

    for col in (
        "new_secrets_count", "total_secrets_count",
        "nuclei_exposures_count", "mantra_count", "secretfinder_count",
    ):
        if _column_exists("scan_runs", col):
            op.drop_column("scan_runs", col)
    if _column_exists("subdomains", "secret_count"):
        op.drop_column("subdomains", "secret_count")
    if _column_exists("hosts", "secret_count"):
        op.drop_column("hosts", "secret_count")
