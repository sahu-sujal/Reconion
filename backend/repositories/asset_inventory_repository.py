"""Asset Inventory repository — Phase 6.3.

Reads the ``asset_inventory`` VIEW (a UNION of classified urls + endpoints +
js_files) to power the Asset Explorer: categorized listing, per-category counts,
global search, and filter facets.

No ORM model backs the view, so queries use parameterized Core SQL. Sort columns
and boolean-trait filters are whitelisted — raw user input is never interpolated
into SQL. Category-specific enrichment (JS size / endpoints extracted / secrets
found) is layered on top via targeted joins.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

# Columns the caller may sort by (whitelist → safe to interpolate).
_SORTABLE = {
    "normalized_url": "normalized_url",
    "host": "host",
    "asset_category": "asset_category",
    "extension": "extension",
    "first_seen": "first_seen",
    "last_seen": "last_seen",
}

# Boolean trait columns the caller may filter on (whitelist).
_TRAIT_COLUMNS = frozenset({
    "is_static", "is_dynamic", "is_api", "is_document", "is_script",
    "is_archive", "is_configuration", "is_backup", "has_parameters",
})

_SELECT_COLUMNS = (
    "id, source_kind, program_id, scope_id, host, normalized_url, asset_category, "
    "extension, mime_type, has_parameters, parameter_count, is_static, is_dynamic, "
    "is_api, is_document, is_script, is_archive, is_configuration, is_backup, "
    "discovery_source, first_seen, last_seen"
)


class AssetInventoryRepository:
    """Query the unified, classified asset inventory."""

    # ------------------------------------------------------------------ #
    # WHERE builder — shared by list / count / facets                      #
    # ------------------------------------------------------------------ #

    def _where(
        self,
        scope_id: uuid.UUID | None,
        program_id: uuid.UUID | None,
        category: str | None,
        search: str | None,
        host: str | None,
        extension: str | None,
        source_kind: str | None,
        discovery_source: str | None,
        trait: str | None,
    ) -> tuple[str, dict]:
        clauses: list[str] = []
        params: dict = {}
        if scope_id is not None:
            clauses.append("scope_id = :scope_id")
            params["scope_id"] = str(scope_id)
        if program_id is not None:
            clauses.append("program_id = :program_id")
            params["program_id"] = str(program_id)
        if category:
            clauses.append("asset_category = :category")
            params["category"] = category
        if search:
            clauses.append("(normalized_url ILIKE :q OR host ILIKE :q)")
            params["q"] = f"%{search}%"
        if host:
            clauses.append("(host = :host OR host ILIKE :host_sub)")
            params["host"] = host
            params["host_sub"] = f"%.{host}"
        if extension:
            clauses.append("extension = :extension")
            params["extension"] = extension.lower()
        if source_kind:
            clauses.append("source_kind = :source_kind")
            params["source_kind"] = source_kind.upper()
        if discovery_source:
            clauses.append("discovery_source ILIKE :discovery_source")
            params["discovery_source"] = f"%{discovery_source}%"
        if trait and trait in _TRAIT_COLUMNS:
            clauses.append(f"{trait} = true")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    # ------------------------------------------------------------------ #
    # List + count                                                         #
    # ------------------------------------------------------------------ #

    def list_assets(
        self,
        db: Session,
        *,
        scope_id: uuid.UUID | None = None,
        program_id: uuid.UUID | None = None,
        category: str | None = None,
        search: str | None = None,
        host: str | None = None,
        extension: str | None = None,
        source_kind: str | None = None,
        discovery_source: str | None = None,
        trait: str | None = None,
        offset: int = 0,
        limit: int = 50,
        sort_by: str = "normalized_url",
        sort_dir: str = "asc",
    ) -> list[dict]:
        where, params = self._where(
            scope_id, program_id, category, search, host, extension,
            source_kind, discovery_source, trait,
        )
        col = _SORTABLE.get(sort_by, "normalized_url")
        direction = "DESC" if sort_dir.lower() == "desc" else "ASC"
        params["limit"] = limit
        params["offset"] = offset
        sql = (
            f"SELECT {_SELECT_COLUMNS} FROM asset_inventory{where} "
            f"ORDER BY {col} {direction} NULLS LAST, normalized_url ASC "
            f"LIMIT :limit OFFSET :offset"
        )
        rows = db.execute(text(sql), params).mappings().all()
        return [dict(r) for r in rows]

    def count_assets(
        self,
        db: Session,
        *,
        scope_id: uuid.UUID | None = None,
        program_id: uuid.UUID | None = None,
        category: str | None = None,
        search: str | None = None,
        host: str | None = None,
        extension: str | None = None,
        source_kind: str | None = None,
        discovery_source: str | None = None,
        trait: str | None = None,
    ) -> int:
        where, params = self._where(
            scope_id, program_id, category, search, host, extension,
            source_kind, discovery_source, trait,
        )
        sql = f"SELECT count(*) FROM asset_inventory{where}"
        return int(db.execute(text(sql), params).scalar() or 0)

    # ------------------------------------------------------------------ #
    # Stats / facets                                                       #
    # ------------------------------------------------------------------ #

    def category_counts(
        self, db: Session, *, scope_id: uuid.UUID | None = None,
        program_id: uuid.UUID | None = None,
    ) -> dict[str, int]:
        """Return ``{asset_category: count}`` for the dashboard + sidebar."""
        where, params = self._where(scope_id, program_id, None, None, None, None, None, None, None)
        sql = (
            "SELECT COALESCE(asset_category, 'UNKNOWN') AS c, count(*) AS n "
            f"FROM asset_inventory{where} GROUP BY 1"
        )
        return {r.c: int(r.n) for r in db.execute(text(sql), params)}

    def total_count(
        self, db: Session, *, scope_id: uuid.UUID | None = None,
        program_id: uuid.UUID | None = None,
    ) -> int:
        return self.count_assets(db, scope_id=scope_id, program_id=program_id)

    def distinct_hosts(
        self, db: Session, *, scope_id: uuid.UUID, limit: int = 2000,
    ) -> list[str]:
        sql = (
            "SELECT DISTINCT host FROM asset_inventory "
            "WHERE scope_id = :scope_id AND host IS NOT NULL "
            "ORDER BY host LIMIT :limit"
        )
        rows = db.execute(text(sql), {"scope_id": str(scope_id), "limit": limit}).all()
        return [r.host for r in rows]

    def distinct_extensions(
        self, db: Session, *, scope_id: uuid.UUID, limit: int = 500,
    ) -> list[str]:
        sql = (
            "SELECT DISTINCT extension FROM asset_inventory "
            "WHERE scope_id = :scope_id AND extension IS NOT NULL "
            "ORDER BY extension LIMIT :limit"
        )
        rows = db.execute(text(sql), {"scope_id": str(scope_id), "limit": limit}).all()
        return [r.extension for r in rows]

    # ------------------------------------------------------------------ #
    # Category-specific enrichment                                         #
    # ------------------------------------------------------------------ #

    def enrich_js(self, db: Session, scope_id: uuid.UUID, js_urls: list[str]) -> dict[str, dict]:
        """For a page of JS URLs, fetch size + endpoints-extracted + secrets-found.

        Returned as ``{js_url: {size_bytes, endpoints_extracted, secrets_found}}``.
        Uses the stored ``source_js_file`` / ``js_file_url`` links — no network.
        """
        if not js_urls:
            return {}
        params = {"scope_id": str(scope_id), "urls": js_urls}
        sql = """
            SELECT jf.url AS url,
                   jf.size_bytes AS size_bytes,
                   (SELECT count(*) FROM endpoints e
                      WHERE e.scope_id = jf.scope_id AND e.source_js_file = jf.url) AS endpoints_extracted,
                   (SELECT count(*) FROM js_secrets s
                      WHERE s.scope_id = jf.scope_id AND s.js_file_url = jf.url) AS secrets_found
            FROM js_files jf
            WHERE jf.scope_id = :scope_id AND jf.url = ANY(:urls)
        """
        out: dict[str, dict] = {}
        for r in db.execute(text(sql), params).mappings():
            out[r["url"]] = {
                "size_bytes": r["size_bytes"],
                "endpoints_extracted": int(r["endpoints_extracted"] or 0),
                "secrets_found": int(r["secrets_found"] or 0),
            }
        return out
