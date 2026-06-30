from __future__ import annotations

import csv
import io
import uuid
from typing import Any

from sqlalchemy import func, literal_column, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from database.models.subdomain import Subdomain
from repositories.base_repository import BaseRepository


class SubdomainRepository(BaseRepository[Subdomain]):
    def __init__(self) -> None:
        super().__init__(Subdomain)

    # ------------------------------------------------------------------ #
    # Filtered list queries                                                 #
    # ------------------------------------------------------------------ #

    def list_by_scope(
        self,
        db: Session,
        scope_id: uuid.UUID,
        offset: int = 0,
        limit: int = 2000,
        after_subdomain: str | None = None,
    ) -> list[Subdomain]:
        stmt = (
            select(Subdomain)
            .where(Subdomain.scope_id == scope_id)
            .order_by(Subdomain.subdomain)
            .limit(limit)
        )
        if after_subdomain:
            stmt = stmt.where(Subdomain.subdomain > after_subdomain)
        elif offset:
            stmt = stmt.offset(offset)
        return list(db.scalars(stmt).all())

    def list_by_program(
        self,
        db: Session,
        program_id: uuid.UUID,
        offset: int = 0,
        limit: int = 2000,
        after_subdomain: str | None = None,
    ) -> list[Subdomain]:
        stmt = (
            select(Subdomain)
            .where(Subdomain.program_id == program_id)
            .order_by(Subdomain.subdomain)
            .limit(limit)
        )
        if after_subdomain:
            stmt = stmt.where(Subdomain.subdomain > after_subdomain)
        elif offset:
            stmt = stmt.offset(offset)
        return list(db.scalars(stmt).all())

    def count_by_scope(self, db: Session, scope_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(Subdomain).where(Subdomain.scope_id == scope_id)
        return int(db.scalar(stmt) or 0)

    # ------------------------------------------------------------------ #
    # Bulk upsert                                                           #
    # ------------------------------------------------------------------ #

    def bulk_upsert(
        self,
        db: Session,
        rows: list[dict[str, Any]],
    ) -> tuple[list[dict], list[dict]]:
        """Insert or update subdomains using ON CONFLICT (scope_id, subdomain).

        Uses PostgreSQL's ``xmax = 0`` trick to distinguish newly inserted rows
        from updated rows without a separate pre-query.

        Returns:
            (new_rows, existing_rows) — each element has ``id`` and ``subdomain`` keys.
        """
        if not rows:
            return [], []

        insert_stmt = pg_insert(Subdomain.__table__).values(rows)
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=["scope_id", "subdomain"],
            set_={
                # Only update last_seen; first_seen and source stay from the original insert
                "last_seen": insert_stmt.excluded.last_seen,
                "updated_at": func.now(),
            },
        ).returning(
            Subdomain.__table__.c.id,
            Subdomain.__table__.c.subdomain,
            literal_column("(xmax = 0)").label("is_new"),
        )

        result = db.execute(upsert_stmt)
        all_rows = result.fetchall()
        db.commit()

        new_rows = [{"id": r.id, "subdomain": r.subdomain} for r in all_rows if r.is_new]
        existing_rows = [
            {"id": r.id, "subdomain": r.subdomain} for r in all_rows if not r.is_new
        ]
        return new_rows, existing_rows

    def bulk_upsert_staged(
        self,
        db: Session,
        rows: list[dict[str, Any]],
    ) -> tuple[list[dict], list[dict]]:
        """COPY rows into a temp table, then upsert with INSERT..SELECT.

        This avoids building one very large VALUES statement and is materially
        faster for high-volume PostgreSQL ingestion. Falls back to ``bulk_upsert``
        only when the installed DBAPI driver does not expose a COPY interface.
        """
        if not rows:
            return [], []

        try:
            return self._bulk_upsert_staged(db, rows)
        except NotImplementedError:
            db.rollback()
            return self.bulk_upsert(db, rows)

    def _bulk_upsert_staged(
        self,
        db: Session,
        rows: list[dict[str, Any]],
    ) -> tuple[list[dict], list[dict]]:
        db.execute(
            text(
                """
                CREATE TEMP TABLE tmp_subdomain_upsert (
                    id uuid NOT NULL,
                    scope_id uuid NOT NULL,
                    program_id uuid NOT NULL,
                    subdomain varchar(255) NOT NULL,
                    source varchar(255),
                    first_seen timestamptz,
                    last_seen timestamptz,
                    created_at timestamptz NOT NULL,
                    updated_at timestamptz NOT NULL
                ) ON COMMIT DROP
                """
            )
        )

        buffer = io.StringIO()
        writer = csv.writer(
            buffer,
            delimiter="\t",
            lineterminator="\n",
            quoting=csv.QUOTE_MINIMAL,
        )
        for row in rows:
            writer.writerow(
                [
                    row["id"],
                    row["scope_id"],
                    row["program_id"],
                    row["subdomain"],
                    row.get("source") or "",
                    row["first_seen"],
                    row["last_seen"],
                    row["created_at"],
                    row["updated_at"],
                ]
            )
        buffer.seek(0)

        self._copy_buffer_to_temp_table(db, buffer)

        result = db.execute(
            text(
                """
                INSERT INTO subdomains (
                    id,
                    scope_id,
                    program_id,
                    subdomain,
                    source,
                    first_seen,
                    last_seen,
                    created_at,
                    updated_at
                )
                SELECT
                    id,
                    scope_id,
                    program_id,
                    subdomain,
                    NULLIF(source, ''),
                    first_seen,
                    last_seen,
                    created_at,
                    updated_at
                FROM tmp_subdomain_upsert
                ON CONFLICT (scope_id, subdomain) DO UPDATE
                SET
                    last_seen = EXCLUDED.last_seen,
                    updated_at = now()
                RETURNING id, subdomain, (xmax = 0) AS is_new
                """
            )
        )
        all_rows = result.fetchall()
        db.commit()

        new_rows = [{"id": r.id, "subdomain": r.subdomain} for r in all_rows if r.is_new]
        existing_rows = [
            {"id": r.id, "subdomain": r.subdomain} for r in all_rows if not r.is_new
        ]
        return new_rows, existing_rows

    def _copy_buffer_to_temp_table(self, db: Session, buffer: io.StringIO) -> None:
        copy_sql = (
            "COPY tmp_subdomain_upsert ("
            "id, scope_id, program_id, subdomain, source, "
            "first_seen, last_seen, created_at, updated_at"
            ") FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t')"
        )
        connection = db.connection().connection
        driver_connection = getattr(connection, "driver_connection", connection)
        cursor = driver_connection.cursor()
        try:
            if hasattr(cursor, "copy_expert"):
                cursor.copy_expert(copy_sql, buffer)
                return
            if hasattr(cursor, "copy"):
                with cursor.copy(copy_sql) as copy:
                    copy.write(buffer.getvalue())
                return
            raise NotImplementedError("PostgreSQL driver does not expose COPY support")
        finally:
            cursor.close()
