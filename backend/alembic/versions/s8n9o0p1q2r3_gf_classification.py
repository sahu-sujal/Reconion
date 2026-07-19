"""Add GF (security-relevance) classification columns to urls and endpoints.

Adds ``gf_tags`` (JSONB array of gf category names), ``gf_tag_count`` and
``gf_classified_at`` to both inventories, plus a GIN index per table so
membership queries (``gf_tags ? 'sqli'``) stay fast, and a partial index for
"has any match" listing.

Also widens the scan_runs scan_type check constraint to accept 'GF'.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "s8n9o0p1q2r3"
down_revision = "r7m8n9o0p1q2"
branch_labels = None
depends_on = None


_TABLES = ("urls", "endpoints")

_SCAN_TYPES_WITHOUT_GF = (
    "'SUBDOMAIN', 'DNS', 'HTTP', 'PORT', 'URL', 'JS', "
    "'CONTENT_DISCOVERY', 'JS_ENDPOINT', 'JS_SECRET', 'TECHNOLOGY', 'SCREENSHOT'"
)
_SCAN_TYPES_WITH_GF = (
    "'SUBDOMAIN', 'DNS', 'HTTP', 'PORT', 'URL', 'JS', "
    "'CONTENT_DISCOVERY', 'JS_ENDPOINT', 'JS_SECRET', 'TECHNOLOGY', "
    "'SCREENSHOT', 'GF'"
)


def _bind():
    return op.get_bind()


def _column_exists(table: str, column: str) -> bool:
    insp = sa.inspect(_bind())
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def _index_exists(table: str, name: str) -> bool:
    insp = sa.inspect(_bind())
    if not insp.has_table(table):
        return False
    return any(i["name"] == name for i in insp.get_indexes(table))


def _constraint_exists(name: str) -> bool:
    insp = sa.inspect(_bind())
    if not insp.has_table("scan_runs"):
        return False
    return any(c["name"] == name for c in insp.get_check_constraints("scan_runs"))


def upgrade() -> None:
    for table in _TABLES:
        if not _column_exists(table, "gf_tags"):
            op.add_column(table, sa.Column(
                "gf_tags", postgresql.JSONB(), nullable=False, server_default="[]"))
        if not _column_exists(table, "gf_tag_count"):
            op.add_column(table, sa.Column(
                "gf_tag_count", sa.Integer(), nullable=False, server_default="0"))
        if not _column_exists(table, "gf_classified_at"):
            op.add_column(table, sa.Column(
                "gf_classified_at", sa.DateTime(timezone=True), nullable=True))

        # GIN index → fast `gf_tags ? 'sqli'` / `gf_tags @> '["xss"]'`.
        gin_name = f"ix_{table}_gf_tags_gin"
        if not _index_exists(table, gin_name):
            op.create_index(gin_name, table, ["gf_tags"], postgresql_using="gin")

        # Partial index → "assets with any GF match" listing/counting.
        matched_name = f"ix_{table}_gf_matched"
        if not _index_exists(table, matched_name):
            op.create_index(
                matched_name, table, ["gf_tag_count"],
                postgresql_where=sa.text("gf_tag_count > 0"),
            )

    if _constraint_exists("ck_scan_runs_scan_type"):
        op.drop_constraint("ck_scan_runs_scan_type", "scan_runs", type_="check")
    op.create_check_constraint(
        "ck_scan_runs_scan_type", "scan_runs",
        f"scan_type IN ({_SCAN_TYPES_WITH_GF})",
    )


def downgrade() -> None:
    op.execute("DELETE FROM scan_runs WHERE scan_type = 'GF'")
    if _constraint_exists("ck_scan_runs_scan_type"):
        op.drop_constraint("ck_scan_runs_scan_type", "scan_runs", type_="check")
    op.create_check_constraint(
        "ck_scan_runs_scan_type", "scan_runs",
        f"scan_type IN ({_SCAN_TYPES_WITHOUT_GF})",
    )

    for table in _TABLES:
        for name in (f"ix_{table}_gf_matched", f"ix_{table}_gf_tags_gin"):
            if _index_exists(table, name):
                op.drop_index(name, table_name=table)
        for col in ("gf_classified_at", "gf_tag_count", "gf_tags"):
            if _column_exists(table, col):
                op.drop_column(table, col)
