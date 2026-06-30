from __future__ import annotations

import csv
import io
import uuid
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from database.models.host import Host
from repositories.base_repository import BaseRepository


class HostRepository(BaseRepository[Host]):
    def __init__(self) -> None:
        super().__init__(Host)

    # ------------------------------------------------------------------
    # Filtered queries
    # ------------------------------------------------------------------

    def list_by_scope(
        self,
        db: Session,
        scope_id: uuid.UUID,
        offset: int = 0,
        limit: int = 2000,
        after_host: str | None = None,
    ) -> list[Host]:
        stmt = (
            select(Host)
            .where(Host.scope_id == scope_id)
            .order_by(Host.host)
            .limit(limit)
        )
        if after_host:
            stmt = stmt.where(Host.host > after_host)
        elif offset:
            stmt = stmt.offset(offset)
        return list(db.scalars(stmt).all())

    def list_live_by_scope(
        self,
        db: Session,
        scope_id: uuid.UUID,
        offset: int = 0,
        limit: int = 2000,
    ) -> list[Host]:
        """Return hosts that have a status_code (probed by httpx)."""
        stmt = (
            select(Host)
            .where(Host.scope_id == scope_id, Host.status_code.isnot(None))
            .order_by(Host.host)
            .offset(offset)
            .limit(limit)
        )
        return list(db.scalars(stmt).all())

    def count_by_scope(self, db: Session, scope_id: uuid.UUID) -> int:
        return int(db.scalar(
            select(func.count()).select_from(Host).where(Host.scope_id == scope_id)
        ) or 0)

    def count_live_by_scope(self, db: Session, scope_id: uuid.UUID) -> int:
        return int(db.scalar(
            select(func.count()).select_from(Host)
            .where(Host.scope_id == scope_id, Host.status_code.isnot(None))
        ) or 0)

    # ------------------------------------------------------------------
    # Bulk HTTP-field update (single round-trip)
    # ------------------------------------------------------------------

    def bulk_update_http_fields(
        self,
        db: Session,
        rows: list[dict[str, Any]],
    ) -> None:
        """Update HTTP metadata for many hosts in a single statement.

        Each row must contain: id, scheme, port, ip, status_code, title,
        content_length, response_time, cdn, waf, last_seen.

        Replaces the previous per-row UPDATE loop (one round-trip per host)
        with a single ``UPDATE ... FROM (VALUES ...)`` so a batch of N hosts
        costs one DB round-trip instead of N.
        """
        if not rows:
            return

        # Chunk to stay well under Postgres' 65535 bind-parameter limit
        # (11 params per row → ~5950 rows max; use 4000 for headroom).
        chunk_size = 4000
        for start in range(0, len(rows), chunk_size):
            chunk = rows[start:start + chunk_size]
            placeholders = []
            flat: dict[str, Any] = {}
            for i, row in enumerate(chunk):
                placeholders.append(
                    f"(CAST(:id_{i} AS uuid), :scheme_{i}, :port_{i}, :ip_{i},"
                    f" :status_code_{i}, :title_{i}, :content_length_{i},"
                    f" :response_time_{i}, :cdn_{i}, :waf_{i}, :last_seen_{i})"
                )
                flat[f"id_{i}"] = str(row["id"])
                flat[f"scheme_{i}"] = row.get("scheme")
                flat[f"port_{i}"] = row.get("port")
                flat[f"ip_{i}"] = row.get("ip")
                flat[f"status_code_{i}"] = row.get("status_code")
                flat[f"title_{i}"] = row.get("title")
                flat[f"content_length_{i}"] = row.get("content_length")
                flat[f"response_time_{i}"] = row.get("response_time")
                flat[f"cdn_{i}"] = bool(row.get("cdn"))
                flat[f"waf_{i}"] = bool(row.get("waf"))
                flat[f"last_seen_{i}"] = row["last_seen"]

            db.execute(
                text(f"""
                    UPDATE hosts AS h SET
                        scheme         = v.scheme,
                        port           = v.port,
                        ip             = v.ip,
                        status_code    = v.status_code,
                        title          = v.title,
                        content_length = v.content_length,
                        response_time  = v.response_time,
                        cdn            = v.cdn,
                        waf            = v.waf,
                        last_seen      = v.last_seen,
                        updated_at     = now()
                    FROM (VALUES {", ".join(placeholders)}) AS v(
                        id, scheme, port, ip, status_code, title,
                        content_length, response_time, cdn, waf, last_seen
                    )
                    WHERE h.id = v.id
                """),
                flat,
            )
        db.commit()

    # ------------------------------------------------------------------
    # Bulk upsert (ON CONFLICT scope_id, host)
    # ------------------------------------------------------------------

    def bulk_upsert_staged(
        self,
        db: Session,
        rows: list[dict[str, Any]],
    ) -> tuple[list[dict], list[dict]]:
        """COPY into temp table then upsert. Falls back to inline upsert."""
        if not rows:
            return [], []
        try:
            return self._bulk_upsert_staged(db, rows)
        except NotImplementedError:
            db.rollback()
            return self._bulk_upsert_inline(db, rows)

    def _bulk_upsert_inline(
        self,
        db: Session,
        rows: list[dict[str, Any]],
    ) -> tuple[list[dict], list[dict]]:
        stmt = pg_insert(Host.__table__).values(rows)
        upsert = stmt.on_conflict_do_update(
            index_elements=["scope_id", "host"],
            set_={
                "last_seen": stmt.excluded.last_seen,
                "updated_at": func.now(),
                "ip": stmt.excluded.ip,
                "scheme": stmt.excluded.scheme,
                "port": stmt.excluded.port,
                "status_code": stmt.excluded.status_code,
                "title": stmt.excluded.title,
                "content_length": stmt.excluded.content_length,
                "response_time": stmt.excluded.response_time,
                "cdn": stmt.excluded.cdn,
                "waf": stmt.excluded.waf,
            },
        ).returning(
            Host.__table__.c.id,
            Host.__table__.c.host,
            Host.__table__.c.asset_id,
        )
        result = db.execute(upsert)
        db.commit()
        all_rows = [{"id": r.id, "host": r.host, "asset_id": r.asset_id} for r in result]
        return all_rows, []

    def _bulk_upsert_staged(
        self,
        db: Session,
        rows: list[dict[str, Any]],
    ) -> tuple[list[dict], list[dict]]:
        db.execute(text("""
            CREATE TEMP TABLE tmp_host_upsert (
                id uuid NOT NULL,
                asset_id uuid NOT NULL,
                program_id uuid NOT NULL,
                scope_id uuid NOT NULL,
                host varchar(255) NOT NULL,
                ip varchar(255),
                scheme varchar(16),
                port integer,
                status_code integer,
                title varchar(512),
                content_length integer,
                response_time float,
                cdn boolean NOT NULL DEFAULT false,
                waf boolean NOT NULL DEFAULT false,
                first_seen timestamptz,
                last_seen timestamptz,
                created_at timestamptz NOT NULL,
                updated_at timestamptz NOT NULL
            ) ON COMMIT DROP
        """))

        buf = io.StringIO()
        writer = csv.writer(buf, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        for row in rows:
            writer.writerow([
                str(row["id"]), str(row["asset_id"]),
                str(row["program_id"]), str(row["scope_id"]),
                row["host"],
                row.get("ip") or r"\N",
                row.get("scheme") or r"\N",
                row["port"] if row.get("port") is not None else r"\N",
                row["status_code"] if row.get("status_code") is not None else r"\N",
                row.get("title") or r"\N",
                row["content_length"] if row.get("content_length") is not None else r"\N",
                row["response_time"] if row.get("response_time") is not None else r"\N",
                "true" if row.get("cdn") else "false",
                "true" if row.get("waf") else "false",
                row["first_seen"], row["last_seen"],
                row["created_at"], row["updated_at"],
            ])
        buf.seek(0)

        copy_sql = (
            "COPY tmp_host_upsert ("
            "id, asset_id, program_id, scope_id, host, ip, scheme, port, "
            "status_code, title, content_length, response_time, cdn, waf, "
            "first_seen, last_seen, created_at, updated_at"
            ") FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t', NULL '\\N')"
        )
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

        result = db.execute(text("""
            INSERT INTO hosts (
                id, asset_id, program_id, scope_id, host, ip, scheme, port,
                status_code, title, content_length, response_time, cdn, waf,
                first_seen, last_seen, created_at, updated_at
            )
            SELECT
                id, asset_id, program_id, scope_id, host, ip, scheme, port,
                status_code, title, content_length, response_time, cdn, waf,
                first_seen, last_seen, created_at, updated_at
            FROM tmp_host_upsert
            ON CONFLICT (scope_id, host) DO UPDATE
            SET
                ip             = EXCLUDED.ip,
                scheme         = EXCLUDED.scheme,
                port           = EXCLUDED.port,
                status_code    = COALESCE(EXCLUDED.status_code, hosts.status_code),
                title          = COALESCE(EXCLUDED.title, hosts.title),
                content_length = COALESCE(EXCLUDED.content_length, hosts.content_length),
                response_time  = COALESCE(EXCLUDED.response_time, hosts.response_time),
                cdn            = EXCLUDED.cdn,
                waf            = EXCLUDED.waf,
                last_seen      = EXCLUDED.last_seen,
                updated_at     = now()
            RETURNING id, host, asset_id, (xmax = 0) AS is_new
        """))
        all_rows = result.fetchall()
        db.commit()

        new_rows = [
            {"id": r.id, "host": r.host, "asset_id": r.asset_id}
            for r in all_rows if r.is_new
        ]
        existing_rows = [
            {"id": r.id, "host": r.host, "asset_id": r.asset_id}
            for r in all_rows if not r.is_new
        ]
        return new_rows, existing_rows
