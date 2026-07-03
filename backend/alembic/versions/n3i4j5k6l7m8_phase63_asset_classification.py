"""Phase 6.3 — Asset Classification Engine & Asset Inventory.

Adds classification columns to the three content tables (urls, endpoints,
js_files) so every discovered asset can be labelled by *what it is* — with no
data duplication (each row is classified in place):

    asset_category, mime_type,
    is_static, is_dynamic, is_api, is_document, is_script,
    is_archive, is_configuration, is_backup

Also adds the missing shared columns where a table lacked them:
    endpoints:  extension, parameter_count, has_parameters
    js_files:   size_bytes

Creates the ``asset_inventory`` VIEW — a UNION of urls + endpoints + js_files
presenting one classified feed to the Asset Explorer. A view means zero copy of
data and no sync problem: it always reflects the underlying rows.

Revision ID: n3i4j5k6l7m8
Revises: m2h3i4j5k6l7
Create Date: 2026-07-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "n3i4j5k6l7m8"
down_revision = "m2h3i4j5k6l7"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    return op.get_bind().execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns WHERE table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": column},
    ).fetchone() is not None


def _add(table: str, column: sa.Column) -> None:
    if not _column_exists(table, column.name):
        op.add_column(table, column)


# Classification columns common to all three content tables.
def _classification_columns() -> list[sa.Column]:
    bool_cols = [
        "is_static", "is_dynamic", "is_api", "is_document", "is_script",
        "is_archive", "is_configuration", "is_backup",
    ]
    cols = [
        sa.Column("asset_category", sa.String(32), nullable=True),
        sa.Column("mime_type", sa.String(128), nullable=True),
    ]
    for name in bool_cols:
        cols.append(
            sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.text("false"))
        )
    return cols


_ASSET_INVENTORY_VIEW = """
CREATE VIEW asset_inventory AS
    SELECT
        u.id                AS id,
        'URL'               AS source_kind,
        u.program_id        AS program_id,
        u.scope_id          AS scope_id,
        u.host              AS host,
        u.normalized_url    AS normalized_url,
        u.asset_category    AS asset_category,
        u.extension         AS extension,
        u.mime_type         AS mime_type,
        u.has_parameters    AS has_parameters,
        u.parameter_count   AS parameter_count,
        u.is_static, u.is_dynamic, u.is_api, u.is_document, u.is_script,
        u.is_archive, u.is_configuration, u.is_backup,
        u.source            AS discovery_source,
        u.first_seen        AS first_seen,
        u.last_seen         AS last_seen
    FROM urls u
    UNION ALL
    SELECT
        e.id, 'ENDPOINT', e.program_id, e.scope_id, e.host, e.normalized_url,
        e.asset_category, e.extension, e.mime_type, e.has_parameters, e.parameter_count,
        e.is_static, e.is_dynamic, e.is_api, e.is_document, e.is_script,
        e.is_archive, e.is_configuration, e.is_backup,
        e.discovery_source, e.first_seen, e.last_seen
    FROM endpoints e
    UNION ALL
    SELECT
        j.id, 'JS', j.program_id, j.scope_id, j.host_ref_host, j.url,
        j.asset_category, j.extension, j.mime_type, false, 0,
        j.is_static, j.is_dynamic, j.is_api, j.is_document, j.is_script,
        j.is_archive, j.is_configuration, j.is_backup,
        j.source, j.first_seen, j.last_seen
    FROM (
        SELECT jf.*, h.host AS host_ref_host
        FROM js_files jf
        LEFT JOIN hosts h ON h.id = jf.host_id
    ) j
"""


def upgrade() -> None:
    # ---- urls: add classification columns (extension/has_parameters exist) ----
    for col in _classification_columns():
        _add("urls", col)

    # ---- endpoints: classification cols + the shared cols it lacked ----
    for col in _classification_columns():
        _add("endpoints", col)
    _add("endpoints", sa.Column("extension", sa.String(32), nullable=True))
    _add("endpoints", sa.Column("parameter_count", sa.Integer(), nullable=False, server_default="0"))
    _add("endpoints", sa.Column("has_parameters", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    # ---- js_files: classification cols + size ----
    for col in _classification_columns():
        _add("js_files", col)
    _add("js_files", sa.Column("size_bytes", sa.BigInteger(), nullable=True))

    # ---- Indexes for per-category listing + high-signal boolean filters ----
    _create_index("ix_urls_asset_category", "urls", "asset_category")
    _create_index("ix_urls_is_api", "urls", "is_api")
    _create_index("ix_urls_is_backup", "urls", "is_backup")
    _create_index("ix_endpoints_asset_category", "endpoints", "asset_category")
    _create_index("ix_endpoints_is_api", "endpoints", "is_api")
    _create_index("ix_endpoints_extension", "endpoints", "extension")
    _create_index("ix_endpoints_has_parameters", "endpoints", "has_parameters")
    _create_index("ix_js_files_asset_category", "js_files", "asset_category")

    # ---- Unified read view ----
    op.execute("DROP VIEW IF EXISTS asset_inventory")
    op.execute(_ASSET_INVENTORY_VIEW)


def _create_index(name: str, table: str, column: str) -> None:
    exists = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE indexname=:n"), {"n": name}
    ).fetchone()
    if not exists:
        op.create_index(name, table, [column])


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS asset_inventory")

    for name in (
        "ix_js_files_asset_category",
        "ix_endpoints_has_parameters", "ix_endpoints_extension",
        "ix_endpoints_is_api", "ix_endpoints_asset_category",
        "ix_urls_is_backup", "ix_urls_is_api", "ix_urls_asset_category",
    ):
        op.execute(f"DROP INDEX IF EXISTS {name}")

    bool_cols = [
        "is_static", "is_dynamic", "is_api", "is_document", "is_script",
        "is_archive", "is_configuration", "is_backup",
    ]
    common = ["asset_category", "mime_type", *bool_cols]

    for col in ("size_bytes", *common):
        if _column_exists("js_files", col):
            op.drop_column("js_files", col)
    for col in ("has_parameters", "parameter_count", "extension", *common):
        if _column_exists("endpoints", col):
            op.drop_column("endpoints", col)
    for col in common:
        if _column_exists("urls", col):
            op.drop_column("urls", col)
