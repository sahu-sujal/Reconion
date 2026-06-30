"""Phase 3 stabilization: subdomain_sources table, unique constraint, scan metrics.

Revision ID: 9d0e1f2a3b4c
Revises: 8c9d0e1f2a3b
Create Date: 2026-06-08

Changes:
    - Deduplicate existing subdomains (keep oldest first_seen per scope+subdomain)
    - Make subdomains.asset_id nullable (bulk upsert no longer requires pre-created assets)
    - Add UNIQUE(scope_id, subdomain) constraint to subdomains
    - Add composite index (scope_id, subdomain) + first_seen + last_seen indexes
    - Create subdomain_sources table (proper per-tool source tracking)
    - Add scan metric columns to scan_runs:
        subfinder_count, assetfinder_count, merged_count, unique_count,
        resolved_count, new_count, existing_count
    - Add raw_records_found to tool_executions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "9d0e1f2a3b4c"
down_revision = "8c9d0e1f2a3b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. Deduplicate subdomains — keep the row with the oldest first_seen  #
    #    (or lowest id as tiebreaker) so the unique constraint can be added #
    # ------------------------------------------------------------------ #
    op.execute(
        """
        DELETE FROM subdomains
        WHERE id NOT IN (
            SELECT DISTINCT ON (scope_id, subdomain) id
            FROM subdomains
            ORDER BY scope_id, subdomain, first_seen ASC NULLS LAST, id ASC
        )
        """
    )

    # ------------------------------------------------------------------ #
    # 2. Make asset_id nullable — bulk upserts no longer need a pre-       #
    #    existing Asset row; assets remain optional                         #
    # ------------------------------------------------------------------ #
    op.alter_column("subdomains", "asset_id", nullable=True)

    # ------------------------------------------------------------------ #
    # 3. Unique constraint + indexes on subdomains                          #
    # ------------------------------------------------------------------ #
    op.create_unique_constraint(
        "uq_subdomains_scope_subdomain", "subdomains", ["scope_id", "subdomain"]
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_subdomains_scope_id_subdomain "
        "ON subdomains (scope_id, subdomain)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_subdomains_first_seen "
        "ON subdomains (first_seen)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_subdomains_last_seen "
        "ON subdomains (last_seen)"
    )

    # ------------------------------------------------------------------ #
    # 4. subdomain_sources — proper per-tool, per-scan source tracking     #
    # ------------------------------------------------------------------ #
    op.create_table(
        "subdomain_sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "subdomain_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subdomains.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scan_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scan_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_subdomain_sources_subdomain_id", "subdomain_sources", ["subdomain_id"]
    )
    op.create_index(
        "ix_subdomain_sources_scan_run_id", "subdomain_sources", ["scan_run_id"]
    )
    op.create_index(
        "ix_subdomain_sources_tool_name", "subdomain_sources", ["tool_name"]
    )
    op.create_unique_constraint(
        "uq_subdomain_sources_subdomain_tool_scan",
        "subdomain_sources",
        ["subdomain_id", "tool_name", "scan_run_id"],
    )

    # ------------------------------------------------------------------ #
    # 5. Scan-level metric columns on scan_runs                            #
    # ------------------------------------------------------------------ #
    for col_name in (
        "subfinder_count",
        "assetfinder_count",
        "merged_count",
        "unique_count",
        "resolved_count",
        "new_count",
        "existing_count",
    ):
        op.add_column(
            "scan_runs",
            sa.Column(col_name, sa.Integer(), nullable=False, server_default="0"),
        )

    # ------------------------------------------------------------------ #
    # 6. Tool-level raw count on tool_executions                           #
    # ------------------------------------------------------------------ #
    op.add_column(
        "tool_executions",
        sa.Column(
            "raw_records_found", sa.Integer(), nullable=False, server_default="0"
        ),
    )


def downgrade() -> None:
    op.drop_column("tool_executions", "raw_records_found")

    for col_name in (
        "subfinder_count",
        "assetfinder_count",
        "merged_count",
        "unique_count",
        "resolved_count",
        "new_count",
        "existing_count",
    ):
        op.drop_column("scan_runs", col_name)

    op.drop_table("subdomain_sources")

    op.execute("DROP INDEX IF EXISTS ix_subdomains_last_seen")
    op.execute("DROP INDEX IF EXISTS ix_subdomains_first_seen")
    op.execute("DROP INDEX IF EXISTS ix_subdomains_scope_id_subdomain")
    op.drop_constraint("uq_subdomains_scope_subdomain", "subdomains", type_="unique")
    op.alter_column("subdomains", "asset_id", nullable=False)
