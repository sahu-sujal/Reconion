"""Phase 6.3 follow-up — add the CREDENTIAL asset category trait.

Adds the ``is_credential`` classification column to urls / endpoints / js_files
(certificates & private keys — .pem/.key/.crt/.csr/.p12/…), and rebuilds the
``asset_inventory`` view to surface it so the Asset Explorer can list and filter
the new "Credentials & Keys" sensitive category.

Revision ID: p5k6l7m8n9o0
Revises: o4j5k6l7m8n9
Create Date: 2026-07-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "p5k6l7m8n9o0"
down_revision = "o4j5k6l7m8n9"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    return op.get_bind().execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns WHERE table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": column},
    ).fetchone() is not None


def _create_index(name: str, table: str, column: str) -> None:
    exists = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE indexname=:n"), {"n": name}
    ).fetchone()
    if not exists:
        op.create_index(name, table, [column])


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
        u.is_archive, u.is_configuration, u.is_backup, u.is_credential,
        u.source            AS discovery_source,
        u.first_seen        AS first_seen,
        u.last_seen         AS last_seen
    FROM urls u
    UNION ALL
    SELECT
        e.id, 'ENDPOINT', e.program_id, e.scope_id, e.host, e.normalized_url,
        e.asset_category, e.extension, e.mime_type, e.has_parameters, e.parameter_count,
        e.is_static, e.is_dynamic, e.is_api, e.is_document, e.is_script,
        e.is_archive, e.is_configuration, e.is_backup, e.is_credential,
        e.discovery_source, e.first_seen, e.last_seen
    FROM endpoints e
    UNION ALL
    SELECT
        j.id, 'JS', j.program_id, j.scope_id, j.host_ref_host, j.url,
        j.asset_category, j.extension, j.mime_type, false, 0,
        j.is_static, j.is_dynamic, j.is_api, j.is_document, j.is_script,
        j.is_archive, j.is_configuration, j.is_backup, j.is_credential,
        j.source, j.first_seen, j.last_seen
    FROM (
        SELECT jf.*, h.host AS host_ref_host
        FROM js_files jf
        LEFT JOIN hosts h ON h.id = jf.host_id
    ) j
"""

# The pre-6.3-credential view (without is_credential) for downgrade.
_ASSET_INVENTORY_VIEW_OLD = _ASSET_INVENTORY_VIEW.replace(
    ", u.is_backup, u.is_credential,", ", u.is_backup,"
).replace(
    ", e.is_backup, e.is_credential,", ", e.is_backup,"
).replace(
    ", j.is_backup, j.is_credential,", ", j.is_backup,"
)


def upgrade() -> None:
    for table in ("urls", "endpoints", "js_files"):
        if not _column_exists(table, "is_credential"):
            op.add_column(table, sa.Column(
                "is_credential", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    _create_index("ix_urls_is_credential", "urls", "is_credential")
    _create_index("ix_endpoints_is_credential", "endpoints", "is_credential")
    _create_index("ix_js_files_is_credential", "js_files", "is_credential")

    op.execute("DROP VIEW IF EXISTS asset_inventory")
    op.execute(_ASSET_INVENTORY_VIEW)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS asset_inventory")
    op.execute(_ASSET_INVENTORY_VIEW_OLD)

    for name in (
        "ix_js_files_is_credential", "ix_endpoints_is_credential", "ix_urls_is_credential",
    ):
        op.execute(f"DROP INDEX IF EXISTS {name}")

    for table in ("js_files", "endpoints", "urls"):
        if _column_exists(table, "is_credential"):
            op.drop_column(table, "is_credential")
