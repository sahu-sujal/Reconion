from __future__ import annotations

import csv
import io
import json
import re
import uuid
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from database.models.endpoint import Endpoint
from repositories.base_repository import BaseRepository

# Sortable columns exposed to the API (whitelist — never interpolate raw input).
_SORTABLE = {
    "normalized_url": "normalized_url",
    "absolute_url": "absolute_url",
    "host": "host",
    "path": "path",
    "first_seen": "first_seen",
    "last_seen": "last_seen",
    "created_at": "created_at",
}


class EndpointRepository(BaseRepository[Endpoint]):
    """Data access for the unified endpoint inventory (Phase 6.1).

    Deduplication key is ``(scope_id, normalized_url)``. On conflict the row's
    ``last_seen`` advances and ``discovery_tools`` is *unioned* with the newly
    discovered tools (so an endpoint found again by another extractor records
    both) — ``first_seen`` is never overwritten.
    """

    def __init__(self) -> None:
        super().__init__(Endpoint)

    # ------------------------------------------------------------------
    # Filtered list queries (pagination + search + sorting)
    # ------------------------------------------------------------------

    def _apply_filters(
        self,
        stmt,
        search: str | None,
        host: str | None,
        tool: str | None,
        source_js: str | None,
    ):
        if search:
            like = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Endpoint.normalized_url.ilike(like),
                    Endpoint.path.ilike(like),
                    Endpoint.host.ilike(like),
                )
            )
        if host:
            stmt = stmt.where(self._domain_clause(host))
        if tool:
            # discovery_tools is a JSONB array — match membership.
            stmt = stmt.where(Endpoint.discovery_tools.op("?")(tool.upper()))
        if source_js:
            stmt = stmt.where(Endpoint.source_js_file.ilike(f"%{source_js}%"))
        return stmt

    def list_by_scope(
        self,
        db: Session,
        scope_id: uuid.UUID,
        offset: int = 0,
        limit: int = 2000,
        search: str | None = None,
        host: str | None = None,
        tool: str | None = None,
        source_js: str | None = None,
        sort_by: str = "normalized_url",
        sort_dir: str = "asc",
    ) -> list[Endpoint]:
        column = _SORTABLE.get(sort_by, "normalized_url")
        direction = "DESC" if sort_dir.lower() == "desc" else "ASC"
        stmt = select(Endpoint).where(Endpoint.scope_id == scope_id)
        stmt = self._apply_filters(stmt, search, host, tool, source_js)
        stmt = stmt.order_by(text(f"{column} {direction}")).offset(offset).limit(limit)
        return list(db.scalars(stmt).all())

    def count_by_scope(
        self,
        db: Session,
        scope_id: uuid.UUID,
        search: str | None = None,
        host: str | None = None,
        tool: str | None = None,
        source_js: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(Endpoint).where(Endpoint.scope_id == scope_id)
        stmt = self._apply_filters(stmt, search, host, tool, source_js)
        return int(db.scalar(stmt) or 0)

    def list_by_host_value(
        self,
        db: Session,
        scope_id: uuid.UUID,
        host_value: str,
        offset: int = 0,
        limit: int = 2000,
        search: str | None = None,
        tool: str | None = None,
        source_js: str | None = None,
        sort_by: str = "normalized_url",
        sort_dir: str = "asc",
    ) -> list[Endpoint]:
        """List endpoints whose host equals *host_value* (a subdomain FQDN)."""
        column = _SORTABLE.get(sort_by, "normalized_url")
        direction = "DESC" if sort_dir.lower() == "desc" else "ASC"
        stmt = select(Endpoint).where(
            Endpoint.scope_id == scope_id, Endpoint.host == host_value
        )
        stmt = self._apply_filters(stmt, search, None, tool, source_js)
        stmt = stmt.order_by(text(f"{column} {direction}")).offset(offset).limit(limit)
        return list(db.scalars(stmt).all())

    def count_by_host_value(
        self,
        db: Session,
        scope_id: uuid.UUID,
        host_value: str,
        search: str | None = None,
        tool: str | None = None,
        source_js: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(Endpoint).where(
            Endpoint.scope_id == scope_id, Endpoint.host == host_value
        )
        stmt = self._apply_filters(stmt, search, None, tool, source_js)
        return int(db.scalar(stmt) or 0)

    def count_for_scope(self, db: Session, scope_id: uuid.UUID) -> int:
        return int(
            db.scalar(
                select(func.count()).select_from(Endpoint).where(Endpoint.scope_id == scope_id)
            ) or 0
        )

    def count_for_program(self, db: Session, program_id: uuid.UUID) -> int:
        return int(
            db.scalar(
                select(func.count()).select_from(Endpoint).where(Endpoint.program_id == program_id)
            ) or 0
        )

    def endpoints_per_host(
        self, db: Session, scope_id: uuid.UUID, limit: int = 100
    ) -> dict[str, int]:
        """Top hosts by endpoint count for the scope's dashboard."""
        rows = db.execute(
            select(Endpoint.host, func.count())
            .where(Endpoint.scope_id == scope_id, Endpoint.host.isnot(None))
            .group_by(Endpoint.host)
            .order_by(func.count().desc())
            .limit(limit)
        ).fetchall()
        return {r[0]: int(r[1]) for r in rows if r[0]}

    def new_endpoints_since(
        self, db: Session, scope_id: uuid.UUID, since,
    ) -> int:
        """Count endpoints first seen at/after *since* (dashboard 'new')."""
        stmt = select(func.count()).select_from(Endpoint).where(
            Endpoint.scope_id == scope_id, Endpoint.first_seen >= since
        )
        return int(db.scalar(stmt) or 0)

    @staticmethod
    def _domain_clause(domain: str):
        """Match the domain itself OR any subdomain of it (LIKE-escaped)."""
        safe = domain.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return or_(Endpoint.host == domain, Endpoint.host.like(f"%.{safe}", escape="\\"))

    # ------------------------------------------------------------------
    # Bulk upsert (ON CONFLICT scope_id, normalized_url)
    # ------------------------------------------------------------------

    _COLUMNS = (
        "id", "program_id", "scope_id", "host_id", "js_file_id",
        "absolute_url", "normalized_url", "scheme", "host", "path",
        "query", "fragment", "discovery_tools", "discovery_source",
        "source_js_file", "first_seen", "last_seen", "created_at", "updated_at",
    )

    def bulk_upsert(
        self,
        db: Session,
        rows: list[dict[str, Any]],
    ) -> tuple[list[dict], list[dict]]:
        """Upsert endpoint rows; union ``discovery_tools`` on conflict.

        Returns ``(new_rows, existing_rows)`` where each element carries
        ``id``, ``normalized_url`` and ``host_id`` — used for counters and
        per-tool source attribution.
        """
        if not rows:
            return [], []
        # Scope guard: drop out-of-scope endpoints before writing (final safety
        # net independent of the worker's merge-time filtering).
        rows = self.enforce_scope(db, rows, host_key="host")
        if not rows:
            return [], []
        # Deduplicate within the batch on the conflict key, merging discovery
        # tools so a single ON CONFLICT statement never touches a row twice.
        deduped: dict[tuple[Any, Any], dict[str, Any]] = {}
        for row in rows:
            key = (row["scope_id"], row["normalized_url"])
            if key in deduped:
                merged = set(deduped[key]["discovery_tools"]) | set(row["discovery_tools"])
                deduped[key]["discovery_tools"] = sorted(merged)
            else:
                deduped[key] = dict(row)
                deduped[key]["discovery_tools"] = sorted(set(row["discovery_tools"]))
        rows = list(deduped.values())

        try:
            return self._bulk_upsert_staged(db, rows)
        except NotImplementedError:
            db.rollback()
            return self._bulk_upsert_inline(db, rows)

    def _bulk_upsert_staged(
        self,
        db: Session,
        rows: list[dict[str, Any]],
    ) -> tuple[list[dict], list[dict]]:
        db.execute(text("""
            CREATE TEMP TABLE tmp_endpoint_upsert (
                id uuid NOT NULL,
                program_id uuid NOT NULL,
                scope_id uuid NOT NULL,
                host_id uuid,
                js_file_id uuid,
                absolute_url text NOT NULL,
                normalized_url text NOT NULL,
                scheme varchar(16),
                host varchar(255),
                path text,
                query text,
                fragment text,
                discovery_tools jsonb NOT NULL,
                discovery_source varchar(32) NOT NULL,
                source_js_file text,
                first_seen timestamptz,
                last_seen timestamptz,
                created_at timestamptz NOT NULL,
                updated_at timestamptz NOT NULL
            ) ON COMMIT DROP
        """))

        buf = io.StringIO()
        writer = csv.writer(buf, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        for r in rows:
            writer.writerow([
                str(r["id"]), str(r["program_id"]), str(r["scope_id"]),
                str(r["host_id"]) if r.get("host_id") else r"\N",
                str(r["js_file_id"]) if r.get("js_file_id") else r"\N",
                r["absolute_url"], r["normalized_url"],
                r.get("scheme") or r"\N",
                r.get("host") or r"\N",
                r.get("path") if r.get("path") is not None else r"\N",
                r.get("query") if r.get("query") is not None else r"\N",
                r.get("fragment") if r.get("fragment") is not None else r"\N",
                json.dumps(r["discovery_tools"]),
                r.get("discovery_source") or "JS_DISCOVERY",
                r.get("source_js_file") or r"\N",
                r["first_seen"], r["last_seen"], r["created_at"], r["updated_at"],
            ])
        buf.seek(0)

        copy_sql = (
            "COPY tmp_endpoint_upsert (" + ", ".join(self._COLUMNS) + ") "
            "FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t', NULL '\\N')"
        )
        self._copy(db, copy_sql, buf)

        # On conflict: advance last_seen, keep first_seen, union discovery_tools
        # (dedup + sort via jsonb aggregation), fill host/js FKs if missing.
        result = db.execute(text("""
            INSERT INTO endpoints (
                id, program_id, scope_id, host_id, js_file_id,
                absolute_url, normalized_url, scheme, host, path,
                query, fragment, discovery_tools, discovery_source,
                source_js_file, first_seen, last_seen, created_at, updated_at
            )
            SELECT
                id, program_id, scope_id, host_id, js_file_id,
                absolute_url, normalized_url, scheme, host, path,
                query, fragment, discovery_tools, discovery_source,
                source_js_file, first_seen, last_seen, created_at, updated_at
            FROM tmp_endpoint_upsert
            ON CONFLICT (scope_id, normalized_url) DO UPDATE
            SET
                last_seen  = EXCLUDED.last_seen,
                host_id    = COALESCE(endpoints.host_id, EXCLUDED.host_id),
                js_file_id = COALESCE(endpoints.js_file_id, EXCLUDED.js_file_id),
                source_js_file = COALESCE(endpoints.source_js_file, EXCLUDED.source_js_file),
                discovery_tools = (
                    SELECT COALESCE(jsonb_agg(DISTINCT t ORDER BY t), '[]'::jsonb)
                    FROM jsonb_array_elements_text(
                        endpoints.discovery_tools || EXCLUDED.discovery_tools
                    ) AS t
                ),
                updated_at = now()
            RETURNING id, normalized_url, host_id, (xmax = 0) AS is_new
        """))
        all_rows = result.fetchall()
        db.commit()
        return self._split(all_rows)

    def _bulk_upsert_inline(
        self,
        db: Session,
        rows: list[dict[str, Any]],
    ) -> tuple[list[dict], list[dict]]:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        chunk = 2000
        if len(rows) > chunk:
            new_all: list[dict] = []
            existing_all: list[dict] = []
            for start in range(0, len(rows), chunk):
                n, e = self._bulk_upsert_inline(db, rows[start:start + chunk])
                new_all.extend(n)
                existing_all.extend(e)
            return new_all, existing_all

        stmt = pg_insert(Endpoint.__table__).values(rows)
        # Union existing + incoming discovery_tools, dedup + sort.
        merged_tools = text("""
            (SELECT COALESCE(jsonb_agg(DISTINCT t ORDER BY t), '[]'::jsonb)
             FROM jsonb_array_elements_text(
                 endpoints.discovery_tools || excluded.discovery_tools) AS t)
        """)
        upsert = stmt.on_conflict_do_update(
            index_elements=["scope_id", "normalized_url"],
            set_={
                "last_seen": stmt.excluded.last_seen,
                "host_id": func.coalesce(Endpoint.__table__.c.host_id, stmt.excluded.host_id),
                "js_file_id": func.coalesce(Endpoint.__table__.c.js_file_id, stmt.excluded.js_file_id),
                "source_js_file": func.coalesce(
                    Endpoint.__table__.c.source_js_file, stmt.excluded.source_js_file
                ),
                "discovery_tools": merged_tools,
                "updated_at": func.now(),
            },
        ).returning(
            Endpoint.__table__.c.id,
            Endpoint.__table__.c.normalized_url,
            Endpoint.__table__.c.host_id,
            text("(xmax = 0) AS is_new"),
        )
        result = db.execute(upsert)
        all_rows = result.fetchall()
        db.commit()
        return self._split(all_rows)

    @staticmethod
    def _split(all_rows) -> tuple[list[dict], list[dict]]:
        new_rows, existing_rows = [], []
        for r in all_rows:
            entry = {"id": r.id, "normalized_url": r.normalized_url, "host_id": r.host_id}
            (new_rows if r.is_new else existing_rows).append(entry)
        return new_rows, existing_rows

    @staticmethod
    def _copy(db: Session, copy_sql: str, buf: io.StringIO) -> None:
        conn = db.connection().connection
        drv = getattr(conn, "driver_connection", conn)
        cur = drv.cursor()
        try:
            if hasattr(cur, "copy_expert"):
                cur.copy_expert(copy_sql, buf)
            elif hasattr(cur, "copy"):
                with cur.copy(copy_sql) as cp:
                    cp.write(buf.getvalue())
            else:
                raise NotImplementedError("No COPY support")
        finally:
            cur.close()

    # ------------------------------------------------------------------
    # Per-tool source attribution (bulk, idempotent)
    # ------------------------------------------------------------------

    def bulk_insert_sources(
        self,
        db: Session,
        rows: list[dict[str, Any]],
    ) -> None:
        """Insert endpoint_sources rows ON CONFLICT DO NOTHING.

        Each row: {endpoint_id, tool_name}.
        """
        if not rows:
            return
        chunk = 5000
        for start in range(0, len(rows), chunk):
            db.execute(
                text("""
                    INSERT INTO endpoint_sources (id, endpoint_id, tool_name, created_at)
                    VALUES (gen_random_uuid(), :endpoint_id, :tool_name, now())
                    ON CONFLICT (endpoint_id, tool_name) DO NOTHING
                """),
                rows[start:start + chunk],
            )
        db.commit()
