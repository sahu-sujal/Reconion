"""Allow CLASSIFICATION as a standalone scan_type.

Asset classification (Phase 6.3) previously ran only as an automatic pipeline
hook after JS-endpoint discovery. This adds ``CLASSIFICATION`` to the
``ck_scan_runs_scan_type`` check constraint so it can be dispatched as a manual,
standalone scan (idempotent — it recomputes the same classification columns).

Revision ID: u0p1q2r3s4t5
Revises: t9o0p1q2r3s4
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "u0p1q2r3s4t5"
down_revision = "t9o0p1q2r3s4"
branch_labels = None
depends_on = None

# Mirror the model's CheckConstraint (database/models/scan_run.py).
_SCAN_TYPES_WITHOUT_CLASSIFICATION = (
    "'SUBDOMAIN', 'DNS', 'HTTP', 'PORT', 'URL', 'JS', "
    "'CONTENT_DISCOVERY', 'JS_ENDPOINT', 'JS_SECRET', 'TECHNOLOGY', "
    "'SCREENSHOT', 'GF'"
)
_SCAN_TYPES_WITH_CLASSIFICATION = (
    "'SUBDOMAIN', 'DNS', 'HTTP', 'PORT', 'URL', 'JS', "
    "'CONTENT_DISCOVERY', 'JS_ENDPOINT', 'JS_SECRET', 'TECHNOLOGY', "
    "'SCREENSHOT', 'GF', 'CLASSIFICATION'"
)


def _constraint_exists(name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("scan_runs"):
        return False
    return any(c["name"] == name for c in insp.get_check_constraints("scan_runs"))


def upgrade() -> None:
    if _constraint_exists("ck_scan_runs_scan_type"):
        op.drop_constraint("ck_scan_runs_scan_type", "scan_runs", type_="check")
    op.create_check_constraint(
        "ck_scan_runs_scan_type", "scan_runs",
        f"scan_type IN ({_SCAN_TYPES_WITH_CLASSIFICATION})",
    )


def downgrade() -> None:
    if _constraint_exists("ck_scan_runs_scan_type"):
        op.drop_constraint("ck_scan_runs_scan_type", "scan_runs", type_="check")
    op.create_check_constraint(
        "ck_scan_runs_scan_type", "scan_runs",
        f"scan_type IN ({_SCAN_TYPES_WITHOUT_CLASSIFICATION})",
    )
