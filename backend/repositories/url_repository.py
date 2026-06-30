from __future__ import annotations

import csv
import io
import uuid
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from database.models.url import URL
from repositories.base_repository import BaseRepository

# Sortable columns exposed to the API (whitelist — never interpolate raw input).
_SORTABLE = {
    "normalized_url": "normalized_url",
    "url": "url",
    "depth": "depth",
    "parameter_count": "parameter_count",
    "extension": "extension",
    "first_seen": "first_seen",
    "last_seen": "last_seen",
    "created_at": "created_at",
}


class URLRepository(BaseRepository[URL]):
    def __init__(self) -> None:
        super().__init__(URL)

    # ------------------------------------------------------------------
    # Filtered list queries (pagination + search + sorting)
    # ------------------------------------------------------------------

    def list_by_scope(
        self,
        db: Session,
        scope_id: uuid.UUID,
        offset: int = 0,
        limit: int = 2000,
        search: str | None = None,
        source: str | None = None,
        host: str | None = None,
        sort_by: str = "normalized_url",
        sort_dir: str = "asc",
    ) -> list[URL]:
        column = _SORTABLE.get(sort_by, "normalized_url")
        direction = "DESC" if sort_dir.lower() == "desc" else "ASC"

        stmt = select(URL).where(URL.scope_id == scope_id)
        if search:
            stmt = stmt.where(URL.normalized_url.ilike(f"%{search}%"))
        if source:
            stmt = stmt.where(URL.source.ilike(f"%{source}%"))
        if host:
            stmt = stmt.where(self._domain_clause(host))
        stmt = stmt.order_by(text(f"{column} {direction}")).offset(offset).limit(limit)
        return list(db.scalars(stmt).all())

    def count_by_scope(
        self,
        db: Session,
        scope_id: uuid.UUID,
        search: str | None = None,
        source: str | None = None,
        host: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(URL).where(URL.scope_id == scope_id)
        if search:
            stmt = stmt.where(URL.normalized_url.ilike(f"%{search}%"))
        if source:
            stmt = stmt.where(URL.source.ilike(f"%{source}%"))
        if host:
            stmt = stmt.where(self._domain_clause(host))
        return int(db.scalar(stmt) or 0)

    @staticmethod
    def _domain_clause(domain: str):
        """Match the domain itself OR any of its subdomains.

        ``ortto.com`` matches ``ortto.com`` and ``help.ortto.com`` but not
        ``notortto.com`` (the leading dot on the suffix prevents that). LIKE
        wildcards in *domain* are escaped so it is matched literally.
        """
        from sqlalchemy import or_

        safe = domain.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return or_(URL.host == domain, URL.host.like(f"%.{safe}", escape="\\"))

    def distinct_hosts_by_scope(self, db: Session, scope_id: uuid.UUID) -> list[str]:
        """Return the sorted unique list of hosts that have at least one URL."""
        rows = db.execute(
            select(URL.host)
            .where(URL.scope_id == scope_id, URL.host.isnot(None))
            .distinct()
            .order_by(URL.host)
        ).fetchall()
        return [r[0] for r in rows if r[0]]

    # ------------------------------------------------------------------
    # Bulk upsert (ON CONFLICT scope_id, normalized_url)
    # ------------------------------------------------------------------

    def bulk_upsert(
        self,
        db: Session,
        rows: list[dict[str, Any]],
    ) -> tuple[list[dict], list[dict]]:
        """COPY rows into a temp table then upsert. Falls back to inline upsert.

        Each row must carry every column of the urls table (see worker).
        Returns ``(new_rows, existing_rows)`` where each element has
        ``id``, ``normalized_url`` and ``host_id`` keys — used to bump counters
        and write per-tool source attribution.
        """
        if not rows:
            return [], []
        # Deduplicate within the batch on the conflict key (latest wins) so a
        # single ON CONFLICT statement never touches the same row twice.
        deduped: dict[tuple[Any, Any], dict[str, Any]] = {}
        for row in rows:
            deduped[(row["scope_id"], row["normalized_url"])] = row
        rows = list(deduped.values())

        try:
            return self._bulk_upsert_staged(db, rows)
        except NotImplementedError:
            db.rollback()
            return self._bulk_upsert_inline(db, rows)

    _COLUMNS = (
        "id", "program_id", "scope_id", "host_id", "url", "normalized_url",
        "scheme", "host", "path", "query", "fragment", "extension",
        "directory", "filename", "depth", "parameter_count", "has_parameters",
        "status", "source", "first_seen", "last_seen", "created_at", "updated_at",
    )

    def _bulk_upsert_staged(
        self,
        db: Session,
        rows: list[dict[str, Any]],
    ) -> tuple[list[dict], list[dict]]:
        db.execute(text("""
            CREATE TEMP TABLE tmp_url_upsert (
                id uuid NOT NULL,
                program_id uuid NOT NULL,
                scope_id uuid NOT NULL,
                host_id uuid,
                url text NOT NULL,
                normalized_url text NOT NULL,
                scheme varchar(16),
                host varchar(255),
                path text,
                query text,
                fragment text,
                extension varchar(32),
                directory text,
                filename varchar(512),
                depth integer NOT NULL,
                parameter_count integer NOT NULL,
                has_parameters boolean NOT NULL,
                status varchar(64),
                source varchar(255),
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
                r["url"], r["normalized_url"],
                r.get("scheme") or r"\N",
                r.get("host") or r"\N",
                r.get("path") if r.get("path") is not None else r"\N",
                r.get("query") if r.get("query") is not None else r"\N",
                r.get("fragment") if r.get("fragment") is not None else r"\N",
                r.get("extension") or r"\N",
                r.get("directory") if r.get("directory") is not None else r"\N",
                r.get("filename") or r"\N",
                int(r.get("depth") or 0),
                int(r.get("parameter_count") or 0),
                "true" if r.get("has_parameters") else "false",
                r.get("status") or r"\N",
                r.get("source") or r"\N",
                r["first_seen"], r["last_seen"], r["created_at"], r["updated_at"],
            ])
        buf.seek(0)

        copy_sql = (
            "COPY tmp_url_upsert (" + ", ".join(self._COLUMNS) + ") "
            "FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t', NULL '\\N')"
        )
        self._copy(db, copy_sql, buf)

        result = db.execute(text("""
            INSERT INTO urls (
                id, program_id, scope_id, host_id, url, normalized_url,
                scheme, host, path, query, fragment, extension,
                directory, filename, depth, parameter_count, has_parameters,
                status, source, first_seen, last_seen, created_at, updated_at
            )
            SELECT
                id, program_id, scope_id, host_id, url, normalized_url,
                scheme, host, path, query, fragment, extension,
                directory, filename, depth, parameter_count, has_parameters,
                status, source, first_seen, last_seen, created_at, updated_at
            FROM tmp_url_upsert
            ON CONFLICT (scope_id, normalized_url) DO UPDATE
            SET
                last_seen  = EXCLUDED.last_seen,
                host_id    = COALESCE(urls.host_id, EXCLUDED.host_id),
                status     = COALESCE(EXCLUDED.status, urls.status),
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

        stmt = pg_insert(URL.__table__).values(rows)
        upsert = stmt.on_conflict_do_update(
            index_elements=["scope_id", "normalized_url"],
            set_={
                "last_seen": stmt.excluded.last_seen,
                "host_id": func.coalesce(URL.__table__.c.host_id, stmt.excluded.host_id),
                "updated_at": func.now(),
            },
        ).returning(
            URL.__table__.c.id,
            URL.__table__.c.normalized_url,
            URL.__table__.c.host_id,
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
        """Insert url_sources rows ON CONFLICT DO NOTHING.

        Each row: {url_id, tool_name}.
        """
        if not rows:
            return
        chunk = 5000
        for start in range(0, len(rows), chunk):
            db.execute(
                text("""
                    INSERT INTO url_sources (id, url_id, tool_name, created_at)
                    VALUES (gen_random_uuid(), :url_id, :tool_name, now())
                    ON CONFLICT (url_id, tool_name) DO NOTHING
                """),
                rows[start:start + chunk],
            )
        db.commit()
