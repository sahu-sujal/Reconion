"""Replace oversized btree dedup keys on urls/endpoints with hash indexes.

A btree entry cannot exceed ~2704 bytes, but ``normalized_url`` is an unbounded
``Text`` column fed by crawlers that routinely emit multi-kilobyte URLs (long
base64 query values, tracking blobs, data-ish paths). A single such URL raised
``ProgramLimitExceeded`` and aborted the entire upsert batch, so one
pathological URL cost the scan every URL it found.

Fix: index ``digest(normalized_url, 'sha256')`` instead of the raw text. The
hash is fixed-width, so the size ceiling disappears while dedup stays exact on
the full value (SHA-256, not a truncation). ``normalized_url`` itself is left
untouched — nothing is lost or shortened.

Both tables are covered. ``endpoints`` has the identical column, constraint and
upsert shape and is the phase immediately downstream of ``urls``, so fixing
only ``urls`` would move the same crash one phase later.

Non-unique lookup indexes on the same column share the ceiling and are rebuilt
the same way.
"""
from __future__ import annotations

from alembic import op

revision = "t9o0p1q2r3s4"
down_revision = "s8n9o0p1q2r3"
branch_labels = None
depends_on = None

_DIGEST = "digest(normalized_url, 'sha256')"


def upgrade() -> None:
    # digest() lives in pgcrypto.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # Existing rows cannot violate the new unique index: the old constraint
    # already enforced the same (scope_id, normalized_url) pair, and equal text
    # hashes equal. Dropping first and rebuilding is therefore safe.
    for table, uniq in (
        ("urls", "uq_urls_scope_normalized"),
        ("endpoints", "uq_endpoints_scope_normalized"),
    ):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {uniq}")
        op.execute(f"DROP INDEX IF EXISTS {uniq}")
        op.execute(
            f"CREATE UNIQUE INDEX {uniq}_hash ON {table} (scope_id, {_DIGEST})"
        )

    # Plain lookup indexes on the same unbounded column share the ceiling.
    for old in (
        "ix_urls_normalized_url",
        "ix_urls_program_id_normalized",
        "ix_urls_host_id_normalized",
        "ix_endpoints_normalized_url",
        "ix_endpoints_program_id_normalized",
        "ix_endpoints_scope_id_normalized",
        "ix_endpoints_host_id_normalized",
    ):
        op.execute(f"DROP INDEX IF EXISTS {old}")

    for table, prefix in (("urls", "ix_urls"), ("endpoints", "ix_endpoints")):
        op.execute(
            f"CREATE INDEX {prefix}_program_id_normalized_hash "
            f"ON {table} (program_id, {_DIGEST})"
        )
        op.execute(
            f"CREATE INDEX {prefix}_host_id_normalized_hash "
            f"ON {table} (host_id, {_DIGEST})"
        )
    op.execute(
        f"CREATE INDEX ix_endpoints_scope_id_normalized_hash "
        f"ON endpoints (scope_id, {_DIGEST})"
    )


def downgrade() -> None:
    for idx in (
        "ix_urls_host_id_normalized_hash",
        "ix_urls_program_id_normalized_hash",
        "ix_endpoints_host_id_normalized_hash",
        "ix_endpoints_program_id_normalized_hash",
        "ix_endpoints_scope_id_normalized_hash",
        "uq_urls_scope_normalized_hash",
        "uq_endpoints_scope_normalized_hash",
    ):
        op.execute(f"DROP INDEX IF EXISTS {idx}")

    # Reverting reintroduces the size ceiling; rows whose normalized_url is too
    # long for a btree entry must go first or the index build fails.
    for table in ("urls", "endpoints"):
        op.execute(f"DELETE FROM {table} WHERE octet_length(normalized_url) > 2000")

    op.execute("CREATE INDEX ix_urls_normalized_url ON urls (normalized_url)")
    op.execute(
        "CREATE INDEX ix_urls_program_id_normalized ON urls (program_id, normalized_url)"
    )
    op.execute(
        "CREATE INDEX ix_urls_host_id_normalized ON urls (host_id, normalized_url)"
    )
    op.execute(
        "ALTER TABLE urls ADD CONSTRAINT uq_urls_scope_normalized "
        "UNIQUE (scope_id, normalized_url)"
    )

    op.execute("CREATE INDEX ix_endpoints_normalized_url ON endpoints (normalized_url)")
    op.execute(
        "CREATE INDEX ix_endpoints_program_id_normalized "
        "ON endpoints (program_id, normalized_url)"
    )
    op.execute(
        "CREATE INDEX ix_endpoints_scope_id_normalized "
        "ON endpoints (scope_id, normalized_url)"
    )
    op.execute(
        "CREATE INDEX ix_endpoints_host_id_normalized "
        "ON endpoints (host_id, normalized_url)"
    )
    op.execute(
        "ALTER TABLE endpoints ADD CONSTRAINT uq_endpoints_scope_normalized "
        "UNIQUE (scope_id, normalized_url)"
    )
