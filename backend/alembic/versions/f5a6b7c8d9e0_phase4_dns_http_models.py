"""Phase 4 — DNS + HTTP models, extended host columns, new scan_run metrics.

Creates:
  - dns_records table
  - http_responses table

Alters:
  - hosts: add scheme, port, content_length, response_time, title widened,
           unique constraint (scope_id, host)
  - scan_runs: add dnsx_count, resolved_count, new_hosts_count,
               httpx_count, live_count, new_live_count

Adds indexes per spec (Part 10).

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-06-10
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
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
    # hosts — new columns
    # ------------------------------------------------------------------
    if not _column_exists("hosts", "scheme"):
        op.add_column("hosts", sa.Column("scheme", sa.String(16), nullable=True))
    if not _column_exists("hosts", "port"):
        op.add_column("hosts", sa.Column("port", sa.Integer(), nullable=True))
    if not _column_exists("hosts", "content_length"):
        op.add_column("hosts", sa.Column("content_length", sa.Integer(), nullable=True))
    if not _column_exists("hosts", "response_time"):
        op.add_column("hosts", sa.Column("response_time", sa.Float(), nullable=True))

    # Widen title VARCHAR(255) → VARCHAR(512)
    op.alter_column("hosts", "title", type_=sa.String(512), existing_nullable=True)

    if not _constraint_exists("uq_hosts_scope_host"):
        op.create_unique_constraint("uq_hosts_scope_host", "hosts", ["scope_id", "host"])
    if not _index_exists("ix_hosts_port"):
        op.create_index("ix_hosts_port", "hosts", ["port"])

    # ------------------------------------------------------------------
    # scan_runs — DNS + HTTP metric columns
    # ------------------------------------------------------------------
    for col in ("dnsx_count", "resolved_count", "new_hosts_count",
                "httpx_count", "live_count", "new_live_count"):
        if not _column_exists("scan_runs", col):
            op.add_column(
                "scan_runs",
                sa.Column(col, sa.Integer(), nullable=False, server_default="0"),
            )

    # ------------------------------------------------------------------
    # dns_records table
    # ------------------------------------------------------------------
    if not _table_exists("dns_records"):
        op.create_table(
            "dns_records",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("record_type", sa.String(16), nullable=False),
            sa.Column("record_value", sa.Text(), nullable=False),
            sa.Column("ttl", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["scope_id"], ["scopes.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["host_id"], ["hosts.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("host_id", "record_type", "record_value", name="uq_dns_records_host_type_value"),
        )

    for idx, col in [
        ("ix_dns_records_program_id", "program_id"),
        ("ix_dns_records_scope_id", "scope_id"),
        ("ix_dns_records_host_id", "host_id"),
        ("ix_dns_records_record_type", "record_type"),
    ]:
        if not _index_exists(idx):
            op.create_index(idx, "dns_records", [col])

    # ------------------------------------------------------------------
    # http_responses table
    # ------------------------------------------------------------------
    if not _table_exists("http_responses"):
        op.create_table(
            "http_responses",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(512), nullable=True),
            sa.Column("content_length", sa.Integer(), nullable=True),
            sa.Column("server", sa.String(255), nullable=True),
            sa.Column("technologies", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("response_time", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["scope_id"], ["scopes.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["host_id"], ["hosts.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("host_id", "url", name="uq_http_responses_host_url"),
        )

    for idx, col in [
        ("ix_http_responses_program_id", "program_id"),
        ("ix_http_responses_scope_id", "scope_id"),
        ("ix_http_responses_host_id", "host_id"),
        ("ix_http_responses_status_code", "status_code"),
    ]:
        if not _index_exists(idx):
            op.create_index(idx, "http_responses", [col])

    # ------------------------------------------------------------------
    # Extra indexes on technologies (Part 10) — already exist, guard anyway
    # ------------------------------------------------------------------
    for idx, col in [
        ("ix_technologies_program_id", "program_id"),
        ("ix_technologies_scope_id", "scope_id"),
        ("ix_technologies_technology", "technology"),
    ]:
        if not _index_exists(idx):
            op.create_index(idx, "technologies", [col])


def downgrade() -> None:
    for idx in ("ix_technologies_technology", "ix_technologies_scope_id",
                "ix_technologies_program_id"):
        if _index_exists(idx):
            op.drop_index(idx, table_name="technologies")

    for idx in ("ix_http_responses_status_code", "ix_http_responses_host_id",
                "ix_http_responses_scope_id", "ix_http_responses_program_id"):
        if _index_exists(idx):
            op.drop_index(idx, table_name="http_responses")
    if _table_exists("http_responses"):
        op.drop_table("http_responses")

    for idx in ("ix_dns_records_record_type", "ix_dns_records_host_id",
                "ix_dns_records_scope_id", "ix_dns_records_program_id"):
        if _index_exists(idx):
            op.drop_index(idx, table_name="dns_records")
    if _table_exists("dns_records"):
        op.drop_table("dns_records")

    for col in ("new_live_count", "live_count", "httpx_count",
                "new_hosts_count", "resolved_count", "dnsx_count"):
        if _column_exists("scan_runs", col):
            op.drop_column("scan_runs", col)

    if _index_exists("ix_hosts_port"):
        op.drop_index("ix_hosts_port", table_name="hosts")
    if _constraint_exists("uq_hosts_scope_host"):
        op.drop_constraint("uq_hosts_scope_host", "hosts", type_="unique")
    op.alter_column("hosts", "title", type_=sa.String(255), existing_nullable=True)
    for col in ("response_time", "content_length", "port", "scheme"):
        if _column_exists("hosts", col):
            op.drop_column("hosts", col)
