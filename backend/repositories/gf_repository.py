"""GF Intelligence queries — server-side search/filter/sort/paginate.

The GF explorer browses the *union* of two inventories (``urls`` and
``endpoints``) as one logical asset list. Both carry the same GF columns
(``gf_tags``, ``gf_tag_count``) and the same classification columns, so the union
is built in SQL and paginated there — the API never loads the full inventory
into memory.

Filtering on tags uses the JSONB containment operator (``gf_tags @> '["sqli"]'``)
so the per-table GIN indexes are used.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from tools.common.scope_filter import root_domain as _root_domain

#: Columns selected from each inventory, aliased to one common shape.
_URL_SELECT = """
    SELECT
        u.id                AS id,
        'URL'               AS asset_type,
        u.normalized_url    AS url,
        u.host              AS host,
        u.program_id        AS program_id,
        u.scope_id          AS scope_id,
        u.host_id           AS host_id,
        u.gf_tags           AS gf_tags,
        u.gf_tag_count      AS gf_tag_count,
        u.gf_classified_at  AS gf_classified_at,
        u.asset_category    AS asset_category,
        u.mime_type         AS mime_type,
        u.status            AS status,
        u.source            AS discovery_source,
        u.parameter_count   AS parameter_count,
        u.extension         AS extension,
        u.is_api            AS is_api,
        u.first_seen        AS first_seen,
        u.last_seen         AS last_seen
    FROM urls u
"""

_ENDPOINT_SELECT = """
    SELECT
        e.id                AS id,
        'ENDPOINT'          AS asset_type,
        e.absolute_url      AS url,
        e.host              AS host,
        e.program_id        AS program_id,
        e.scope_id          AS scope_id,
        e.host_id           AS host_id,
        e.gf_tags           AS gf_tags,
        e.gf_tag_count      AS gf_tag_count,
        e.gf_classified_at  AS gf_classified_at,
        e.asset_category    AS asset_category,
        e.mime_type         AS mime_type,
        NULL                AS status,
        e.discovery_source  AS discovery_source,
        e.parameter_count   AS parameter_count,
        e.extension         AS extension,
        e.is_api            AS is_api,
        e.first_seen        AS first_seen,
        e.last_seen         AS last_seen
    FROM endpoints e
"""

_SORTABLE = {
    "url": "url",
    "host": "host",
    "asset_type": "asset_type",
    "gf_tag_count": "gf_tag_count",
    "parameter_count": "parameter_count",
    "last_seen": "last_seen",
    "first_seen": "first_seen",
    "gf_classified_at": "gf_classified_at",
}


class GfRepository:
    """Read-side queries powering the GF Intelligence explorer."""

    # ------------------------------------------------------------------
    # Filter construction
    # ------------------------------------------------------------------

    def _build_filters(
        self,
        *,
        alias: str,
        program_ids: list[uuid.UUID] | None,
        scope_ids: list[uuid.UUID] | None,
        hosts: list[str] | None,
        categories: list[str] | None,
        match_all: bool,
        only_matched: bool,
        search: str | None,
        params: dict[str, Any],
        scope_roots: list[str] | None = None,
    ) -> str:
        """Return a WHERE fragment for one inventory table.

        ``alias`` is the table alias used in the SELECT above ('u' or 'e').
        Bind parameters are accumulated into *params* (shared across both
        halves of the UNION, so names are stable).
        """
        clauses: list[str] = []

        if program_ids:
            clauses.append(f"{alias}.program_id = ANY(CAST(:program_ids AS uuid[]))")
            params["program_ids"] = [str(p) for p in program_ids]
        if scope_ids:
            clauses.append(f"{alias}.scope_id = ANY(CAST(:scope_ids AS uuid[]))")
            params["scope_ids"] = [str(s) for s in scope_ids]
        if hosts:
            clauses.append(f"{alias}.host = ANY(CAST(:hosts AS text[]))")
            params["hosts"] = list(hosts)

        if scope_roots:
            # Root-domain guard: keep only assets whose host is the scope root
            # or a subdomain of it ("test.com" keeps test.com / api.test.com,
            # drops cdn.cloudfront.net). Applied on read rather than at write
            # time because the inventory deliberately stores third-party hosts
            # (see UrlRepository.bulk_upsert) — GF Intelligence is a reporting
            # view, so it shows only what is actually in scope.
            # The host may carry a :port, so compare against the port-stripped
            # value. host is indexed; split_part is cheap relative to the
            # gf_tags GIN filter that runs alongside it.
            ors = []
            for i, root in enumerate(scope_roots):
                key = f"root_{i}"
                ors.append(
                    f"(split_part({alias}.host, ':', 1) = :{key}"
                    f" OR split_part({alias}.host, ':', 1) LIKE '%.' || :{key})"
                )
                params[key] = root
            clauses.append("(" + " OR ".join(ors) + ")")

        if categories:
            # @> uses the GIN index. match_all → must contain every tag;
            # otherwise any overlap qualifies.
            if match_all:
                clauses.append(f"{alias}.gf_tags @> CAST(:categories_json AS jsonb)")
                import json as _json
                params["categories_json"] = _json.dumps(list(categories))
            else:
                ors = []
                for i, cat in enumerate(categories):
                    key = f"cat_{i}"
                    ors.append(f"{alias}.gf_tags @> CAST(:{key} AS jsonb)")
                    import json as _json
                    params[key] = _json.dumps([cat])
                clauses.append("(" + " OR ".join(ors) + ")")
        elif only_matched:
            clauses.append(f"{alias}.gf_tag_count > 0")

        if search:
            clauses.append(f"({alias}.host ILIKE :search OR {_url_col(alias)} ILIKE :search)")
            params["search"] = f"%{search}%"

        return (" WHERE " + " AND ".join(clauses)) if clauses else ""

    def _scope_roots(self, db: Session, scope_ids, program_ids) -> list[str]:
        """Resolve the root domains the query is bound to.

        Returns the normalised (wildcard-stripped, lower-cased) target of every
        scope in play, so the caller can restrict results to hosts at or under
        those roots. An unresolvable scope contributes nothing rather than
        silently widening the query.
        """
        if scope_ids:
            where, params = "id = ANY(CAST(:ids AS uuid[]))", {"ids": [str(s) for s in scope_ids]}
        elif program_ids:
            where, params = "program_id = ANY(CAST(:ids AS uuid[]))", {"ids": [str(p) for p in program_ids]}
        else:
            return []
        targets = db.execute(
            text(f"SELECT target FROM scopes WHERE {where}"), params,
        ).scalars().all()
        return sorted({_root_domain(t) for t in targets if t})

    def _root_clause(self, db: Session, scope_ids, program_ids, params: dict[str, Any]) -> str:
        """AND-fragment restricting an unaliased query to in-scope hosts.

        Counterpart to the ``scope_roots`` handling in :meth:`_build_filters`,
        for the aggregate queries that build their own SQL rather than going
        through the UNION helper.
        """
        roots = self._scope_roots(db, scope_ids, program_ids)
        if not roots:
            return ""
        ors = []
        for i, root in enumerate(roots):
            key = f"root_{i}"
            ors.append(
                f"(split_part(host, ':', 1) = :{key}"
                f" OR split_part(host, ':', 1) LIKE '%.' || :{key})"
            )
            params[key] = root
        return " AND (" + " OR ".join(ors) + ")"

    def _union_sql(self, params: dict[str, Any], **filter_kwargs: Any) -> str:
        """Build the filtered UNION ALL over urls + endpoints."""
        asset_types = filter_kwargs.pop("asset_types", None) or []
        halves: list[str] = []
        if not asset_types or "URL" in asset_types:
            where = self._build_filters(alias="u", params=params, **filter_kwargs)
            halves.append(_URL_SELECT + where)
        if not asset_types or "ENDPOINT" in asset_types:
            where = self._build_filters(alias="e", params=params, **filter_kwargs)
            halves.append(_ENDPOINT_SELECT + where)
        if not halves:  # unknown asset_type filter → no rows
            return _URL_SELECT + " WHERE 1 = 0"
        return " UNION ALL ".join(halves)

    # ------------------------------------------------------------------
    # Public queries
    # ------------------------------------------------------------------

    def list_assets(
        self,
        db: Session,
        *,
        program_ids: list[uuid.UUID] | None = None,
        scope_ids: list[uuid.UUID] | None = None,
        hosts: list[str] | None = None,
        asset_types: list[str] | None = None,
        categories: list[str] | None = None,
        match_all: bool = False,
        only_matched: bool = True,
        search: str | None = None,
        sort_by: str = "gf_tag_count",
        sort_dir: str = "desc",
        offset: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        union = self._union_sql(
            params,
            program_ids=program_ids, scope_ids=scope_ids, hosts=hosts,
            asset_types=asset_types, categories=categories, match_all=match_all,
            only_matched=only_matched, search=search,
            scope_roots=self._scope_roots(db, scope_ids, program_ids),
        )
        column = _SORTABLE.get(sort_by, "gf_tag_count")
        direction = "DESC" if str(sort_dir).lower() == "desc" else "ASC"
        params["limit"] = limit
        params["offset"] = offset

        rows = db.execute(
            text(f"""
                SELECT * FROM ({union}) AS a
                ORDER BY {column} {direction} NULLS LAST, url ASC
                LIMIT :limit OFFSET :offset
            """),
            params,
        ).mappings().all()
        return [dict(r) for r in rows]

    def count_assets(self, db: Session, **filters: Any) -> int:
        params: dict[str, Any] = {}
        # Must apply the same root-domain guard as list_assets, or the reported
        # total would not match the rows actually returned.
        filters.setdefault(
            "scope_roots",
            self._scope_roots(db, filters.get("scope_ids"), filters.get("program_ids")),
        )
        union = self._union_sql(params, **filters)
        return int(db.execute(
            text(f"SELECT COUNT(*) FROM ({union}) AS a"), params,
        ).scalar() or 0)

    def get_asset(
        self, db: Session, asset_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        """Fetch one asset by id from either inventory."""
        params = {"id": str(asset_id)}
        row = db.execute(
            text(f"""
                SELECT * FROM (
                    {_URL_SELECT} WHERE u.id = CAST(:id AS uuid)
                    UNION ALL
                    {_ENDPOINT_SELECT} WHERE e.id = CAST(:id AS uuid)
                ) AS a LIMIT 1
            """),
            params,
        ).mappings().first()
        return dict(row) if row else None

    def list_categories(
        self,
        db: Session,
        *,
        program_ids: list[uuid.UUID] | None = None,
        scope_ids: list[uuid.UUID] | None = None,
    ) -> list[dict[str, Any]]:
        """Every GF category present in the data, with per-type asset counts.

        Generated from the stored tags (never hardcoded), so a new pattern file
        shows up here as soon as a GF scan tags something with it.
        """
        params: dict[str, Any] = {}
        scope_clause = ""
        if program_ids:
            scope_clause += " AND program_id = ANY(CAST(:program_ids AS uuid[]))"
            params["program_ids"] = [str(p) for p in program_ids]
        if scope_ids:
            scope_clause += " AND scope_id = ANY(CAST(:scope_ids AS uuid[]))"
            params["scope_ids"] = [str(s) for s in scope_ids]
        scope_clause += self._root_clause(db, scope_ids, program_ids, params)

        rows = db.execute(
            text(f"""
                SELECT
                    tag AS category,
                    COUNT(*)                                  AS asset_count,
                    COUNT(*) FILTER (WHERE kind = 'URL')      AS url_count,
                    COUNT(*) FILTER (WHERE kind = 'ENDPOINT') AS endpoint_count,
                    COUNT(DISTINCT host)                      AS host_count
                FROM (
                    SELECT jsonb_array_elements_text(gf_tags) AS tag,
                           'URL' AS kind, host
                    FROM urls
                    WHERE gf_tag_count > 0 {scope_clause}
                    UNION ALL
                    SELECT jsonb_array_elements_text(gf_tags) AS tag,
                           'ENDPOINT' AS kind, host
                    FROM endpoints
                    WHERE gf_tag_count > 0 {scope_clause}
                ) t
                GROUP BY tag
                ORDER BY asset_count DESC, category ASC
            """),
            params,
        ).mappings().all()
        return [dict(r) for r in rows]

    def statistics(
        self,
        db: Session,
        *,
        program_ids: list[uuid.UUID] | None = None,
        scope_ids: list[uuid.UUID] | None = None,
        top: int = 10,
    ) -> dict[str, Any]:
        """Dashboard aggregates: totals, top categories, per host/program/scope."""
        params: dict[str, Any] = {}
        where = " WHERE 1=1"
        if program_ids:
            where += " AND program_id = ANY(CAST(:program_ids AS uuid[]))"
            params["program_ids"] = [str(p) for p in program_ids]
        if scope_ids:
            where += " AND scope_id = ANY(CAST(:scope_ids AS uuid[]))"
            params["scope_ids"] = [str(s) for s in scope_ids]
        where += self._root_clause(db, scope_ids, program_ids, params)

        base = f"""
            SELECT id, host, program_id, scope_id, gf_tags, gf_tag_count,
                   gf_classified_at
            FROM urls {where}
            UNION ALL
            SELECT id, host, program_id, scope_id, gf_tags, gf_tag_count,
                   gf_classified_at
            FROM endpoints {where}
        """

        totals = db.execute(
            text(f"""
                SELECT
                    COUNT(*)                                            AS total_assets,
                    COUNT(*) FILTER (WHERE gf_classified_at IS NOT NULL) AS classified,
                    COUNT(*) FILTER (WHERE gf_tag_count > 0)             AS matched,
                    COUNT(*) FILTER (WHERE gf_classified_at IS NOT NULL
                                       AND gf_tag_count = 0)             AS unmatched
                FROM ({base}) a
            """),
            params,
        ).mappings().first()

        params_top = dict(params, top=top)

        by_host = db.execute(
            text(f"""
                SELECT host, COUNT(*) AS asset_count
                FROM ({base}) a
                WHERE gf_tag_count > 0 AND host IS NOT NULL
                GROUP BY host ORDER BY asset_count DESC LIMIT :top
            """), params_top,
        ).mappings().all()

        by_program = db.execute(
            text(f"""
                SELECT a.program_id, p.name AS program_name, COUNT(*) AS asset_count
                FROM ({base}) a
                JOIN programs p ON p.id = a.program_id
                WHERE a.gf_tag_count > 0
                GROUP BY a.program_id, p.name
                ORDER BY asset_count DESC LIMIT :top
            """), params_top,
        ).mappings().all()

        by_scope = db.execute(
            text(f"""
                SELECT a.scope_id, s.target AS scope_target, COUNT(*) AS asset_count
                FROM ({base}) a
                JOIN scopes s ON s.id = a.scope_id
                WHERE a.gf_tag_count > 0
                GROUP BY a.scope_id, s.target
                ORDER BY asset_count DESC LIMIT :top
            """), params_top,
        ).mappings().all()

        top_categories = db.execute(
            text(f"""
                SELECT jsonb_array_elements_text(gf_tags) AS category, COUNT(*) AS asset_count
                FROM ({base}) a
                WHERE gf_tag_count > 0
                GROUP BY category ORDER BY asset_count DESC LIMIT :top
            """), params_top,
        ).mappings().all()

        recent = db.execute(
            text(f"""
                SELECT id, host, gf_tags, gf_classified_at
                FROM ({base}) a
                WHERE gf_tag_count > 0 AND gf_classified_at IS NOT NULL
                ORDER BY gf_classified_at DESC LIMIT :top
            """), params_top,
        ).mappings().all()

        return {
            "total_assets": int(totals["total_assets"] or 0),
            "classified_assets": int(totals["classified"] or 0),
            "assets_with_matches": int(totals["matched"] or 0),
            "assets_without_matches": int(totals["unmatched"] or 0),
            "unique_categories": len(self.list_categories(
                db, program_ids=program_ids, scope_ids=scope_ids,
            )),
            "top_categories": [dict(r) for r in top_categories],
            "assets_per_host": [dict(r) for r in by_host],
            "assets_per_program": [dict(r) for r in by_program],
            "assets_per_scope": [dict(r) for r in by_scope],
            "recently_classified": [dict(r) for r in recent],
        }

    def distinct_hosts(
        self,
        db: Session,
        *,
        program_ids: list[uuid.UUID] | None = None,
        scope_ids: list[uuid.UUID] | None = None,
    ) -> list[str]:
        """Hosts that have at least one GF-tagged asset — for filter dropdowns."""
        params: dict[str, Any] = {}
        where = " AND gf_tag_count > 0"
        if program_ids:
            where += " AND program_id = ANY(CAST(:program_ids AS uuid[]))"
            params["program_ids"] = [str(p) for p in program_ids]
        if scope_ids:
            where += " AND scope_id = ANY(CAST(:scope_ids AS uuid[]))"
            params["scope_ids"] = [str(s) for s in scope_ids]
        where += self._root_clause(db, scope_ids, program_ids, params)
        rows = db.execute(
            text(f"""
                SELECT DISTINCT host FROM (
                    SELECT host, program_id, scope_id, gf_tag_count FROM urls
                    UNION ALL
                    SELECT host, program_id, scope_id, gf_tag_count FROM endpoints
                ) a
                WHERE host IS NOT NULL {where}
                ORDER BY host
            """),
            params,
        ).fetchall()
        return [r[0] for r in rows]


def _url_col(alias: str) -> str:
    """The URL column name for a table alias (urls vs endpoints differ)."""
    return "u.normalized_url" if alias == "u" else "e.absolute_url"
