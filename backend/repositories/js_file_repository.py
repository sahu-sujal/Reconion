from __future__ import annotations

import csv
import io
import re
import uuid
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from database.models.js_file import JsFile
from repositories.base_repository import BaseRepository

_SORTABLE = {
    "url": "url",
    "filename": "filename",
    "extension": "extension",
    "first_seen": "first_seen",
    "last_seen": "last_seen",
    "created_at": "created_at",
}


class JsFileRepository(BaseRepository[JsFile]):
    def __init__(self) -> None:
        super().__init__(JsFile)

    # ------------------------------------------------------------------
    # Filtered list queries
    # ------------------------------------------------------------------

    def list_by_scope(
        self,
        db: Session,
        scope_id: uuid.UUID,
        offset: int = 0,
        limit: int = 2000,
        search: str | None = None,
        host: str | None = None,
        sort_by: str = "url",
        sort_dir: str = "asc",
    ) -> list[JsFile]:
        column = _SORTABLE.get(sort_by, "url")
        direction = "DESC" if sort_dir.lower() == "desc" else "ASC"

        stmt = select(JsFile).where(JsFile.scope_id == scope_id)
        if search:
            stmt = stmt.where(JsFile.url.ilike(f"%{search}%"))
        if host:
            stmt = stmt.where(self._host_clause(host))
        stmt = stmt.order_by(text(f"{column} {direction}")).offset(offset).limit(limit)
        return list(db.scalars(stmt).all())

    def count_by_scope(
        self,
        db: Session,
        scope_id: uuid.UUID,
        search: str | None = None,
        host: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(JsFile).where(JsFile.scope_id == scope_id)
        if search:
            stmt = stmt.where(JsFile.url.ilike(f"%{search}%"))
        if host:
            stmt = stmt.where(self._host_clause(host))
        return int(db.scalar(stmt) or 0)

    @staticmethod
    def _host_clause(domain: str):
        """Match js_files whose host is *domain* OR a subdomain of it.

        js_files has no host column, so we match the URL authority directly:
        ``scheme://[anything.]domain[:port]/…``. ``ortto.com`` matches
        ``ortto.com`` and ``help.ortto.com`` but not ``notortto.com``.
        The domain is regex-escaped so dots are matched literally.
        """
        d = re.escape(domain)
        return JsFile.url.op("~")(f"^https?://([^/@]+\\.)?{d}(:[0-9]+)?(/|$)")

    # ------------------------------------------------------------------
    # Streaming iteration (Phase 6.1 — constant memory over 200k+ JS files)
    # ------------------------------------------------------------------

    def iter_scope_js(
        self,
        db: Session,
        scope_id: uuid.UUID,
        batch_size: int = 500,
        after_id: uuid.UUID | None = None,
    ):
        """Yield ``(id, url, host_id)`` tuples for the scope's JS files in batches.

        Uses **keyset pagination** (``WHERE id > :after ORDER BY id LIMIT n``)
        rather than a server-side ``yield_per`` cursor. This keeps memory flat
        *and* survives the ``db.commit()`` the worker issues per batch — a
        streaming cursor is invalidated by an intervening commit
        ("named cursor isn't valid anymore"), keyset pagination is not.

        Pass ``after_id`` (the last processed JS id) to resume mid-way.
        """
        last_id = after_id
        while True:
            stmt = select(JsFile.id, JsFile.url, JsFile.host_id).where(
                JsFile.scope_id == scope_id
            )
            if last_id is not None:
                stmt = stmt.where(JsFile.id > last_id)
            stmt = stmt.order_by(JsFile.id).limit(batch_size)

            rows = db.execute(stmt).all()
            if not rows:
                return
            for row in rows:
                yield row.id, row.url, row.host_id
            last_id = rows[-1].id
            if len(rows) < batch_size:
                return

    def count_scope_js(self, db: Session, scope_id: uuid.UUID) -> int:
        return int(
            db.scalar(
                select(func.count()).select_from(JsFile).where(JsFile.scope_id == scope_id)
            ) or 0
        )

    # ------------------------------------------------------------------
    # Bulk upsert (ON CONFLICT scope_id, url)
    # ------------------------------------------------------------------

    _COLUMNS = (
        "id", "program_id", "scope_id", "host_id", "url",
        "filename", "directory", "extension", "source",
        "first_seen", "last_seen", "created_at", "updated_at",
    )

    def bulk_upsert(
        self,
        db: Session,
        rows: list[dict[str, Any]],
    ) -> tuple[list[dict], list[dict]]:
        if not rows:
            return [], []
        # Scope guard: drop out-of-scope JS files (host derived from the URL).
        rows = self.enforce_scope(db, rows, url_key="url")
        if not rows:
            return [], []
        deduped: dict[tuple[Any, Any], dict[str, Any]] = {}
        for row in rows:
            deduped[(row["scope_id"], row["url"])] = row
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
            CREATE TEMP TABLE tmp_js_upsert (
                id uuid NOT NULL,
                program_id uuid NOT NULL,
                scope_id uuid NOT NULL,
                host_id uuid,
                url text NOT NULL,
                filename varchar(512),
                directory text,
                extension varchar(32),
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
                r["url"],
                r.get("filename") or r"\N",
                r.get("directory") if r.get("directory") is not None else r"\N",
                r.get("extension") or r"\N",
                r.get("source") or r"\N",
                r["first_seen"], r["last_seen"], r["created_at"], r["updated_at"],
            ])
        buf.seek(0)

        copy_sql = (
            "COPY tmp_js_upsert (" + ", ".join(self._COLUMNS) + ") "
            "FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t', NULL '\\N')"
        )
        self._copy(db, copy_sql, buf)

        result = db.execute(text("""
            INSERT INTO js_files (
                id, program_id, scope_id, host_id, url,
                filename, directory, extension, source,
                first_seen, last_seen, created_at, updated_at
            )
            SELECT
                id, program_id, scope_id, host_id, url,
                filename, directory, extension, source,
                first_seen, last_seen, created_at, updated_at
            FROM tmp_js_upsert
            ON CONFLICT (scope_id, url) DO UPDATE
            SET
                last_seen  = EXCLUDED.last_seen,
                host_id    = COALESCE(js_files.host_id, EXCLUDED.host_id),
                updated_at = now()
            RETURNING id, url, host_id, (xmax = 0) AS is_new
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

        chunk = 3000
        if len(rows) > chunk:
            new_all: list[dict] = []
            existing_all: list[dict] = []
            for start in range(0, len(rows), chunk):
                n, e = self._bulk_upsert_inline(db, rows[start:start + chunk])
                new_all.extend(n)
                existing_all.extend(e)
            return new_all, existing_all

        stmt = pg_insert(JsFile.__table__).values(rows)
        upsert = stmt.on_conflict_do_update(
            index_elements=["scope_id", "url"],
            set_={
                "last_seen": stmt.excluded.last_seen,
                "host_id": func.coalesce(JsFile.__table__.c.host_id, stmt.excluded.host_id),
                "updated_at": func.now(),
            },
        ).returning(
            JsFile.__table__.c.id,
            JsFile.__table__.c.url,
            JsFile.__table__.c.host_id,
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
            entry = {"id": r.id, "url": r.url, "host_id": r.host_id}
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

    def bulk_insert_sources(
        self,
        db: Session,
        rows: list[dict[str, Any]],
    ) -> None:
        """Insert js_file_sources rows ON CONFLICT DO NOTHING. Each: {js_file_id, tool_name}."""
        if not rows:
            return
        chunk = 5000
        for start in range(0, len(rows), chunk):
            db.execute(
                text("""
                    INSERT INTO js_file_sources (id, js_file_id, tool_name, created_at)
                    VALUES (gen_random_uuid(), :js_file_id, :tool_name, now())
                    ON CONFLICT (js_file_id, tool_name) DO NOTHING
                """),
                rows[start:start + chunk],
            )
        db.commit()
