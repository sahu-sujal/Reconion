"""Add subdomain_id FK to dns_records for direct subdomain linkage.

Revision ID: g6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Branch Labels: None
Depends On: None
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "g6b7c8d9e0f1"
down_revision = "f5a6b7c8d9e0"
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


def _index_exists(index: str) -> bool:
    result = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname=:i"),
        {"i": index},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    if not _column_exists("dns_records", "subdomain_id"):
        op.add_column(
            "dns_records",
            sa.Column(
                "subdomain_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("subdomains.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    if not _index_exists("ix_dns_records_subdomain_id"):
        op.create_index("ix_dns_records_subdomain_id", "dns_records", ["subdomain_id"])


def downgrade() -> None:
    if _index_exists("ix_dns_records_subdomain_id"):
        op.drop_index("ix_dns_records_subdomain_id", table_name="dns_records")
    if _column_exists("dns_records", "subdomain_id"):
        op.drop_column("dns_records", "subdomain_id")
