"""optimize subdomain indexes for large scans

Revision ID: a0b1c2d3e4f5
Revises: 9d0e1f2a3b4c
Create Date: 2026-06-08
"""

from __future__ import annotations

from alembic import op

revision = "a0b1c2d3e4f5"
down_revision = "9d0e1f2a3b4c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The UNIQUE(scope_id, subdomain) constraint already owns an equivalent btree.
    # Keeping a duplicate non-unique index doubles write amplification during ingest.
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_subdomains_scope_id_subdomain")

        # Useful when listing/searching all subdomains for a program.
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_subdomains_program_id_subdomain "
            "ON subdomains (program_id, subdomain)"
        )

        # Most scans do not create Asset rows for every subdomain; avoid indexing NULLs.
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_subdomains_asset_id")
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_subdomains_asset_id_not_null "
            "ON subdomains (asset_id) WHERE asset_id IS NOT NULL"
        )

        # A full boolean index is low-selectivity and expensive at 10M rows.
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_subdomains_resolved")
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_subdomains_resolved_true "
            "ON subdomains (scope_id, subdomain) WHERE resolved = true"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_subdomains_resolved_true")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_subdomains_asset_id_not_null")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_subdomains_program_id_subdomain")

        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_subdomains_scope_id_subdomain "
            "ON subdomains (scope_id, subdomain)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_subdomains_asset_id "
            "ON subdomains (asset_id)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_subdomains_resolved "
            "ON subdomains (resolved)"
        )
