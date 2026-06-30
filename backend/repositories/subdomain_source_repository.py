from __future__ import annotations

import csv
import io
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from database.models.subdomain_source import SubdomainSource
from repositories.base_repository import BaseRepository


class SubdomainSourceRepository(BaseRepository[SubdomainSource]):
    def __init__(self) -> None:
        super().__init__(SubdomainSource)

    def bulk_insert_sources(
        self, db: Session, source_records: list[dict[str, Any]]
    ) -> None:
        """Bulk-insert source records, silently ignoring duplicates.

        A duplicate is (subdomain_id, tool_name, scan_run_id) that already exists
        from a previous scan — handled by the unique constraint with DO NOTHING.
        """
        if not source_records:
            return
        stmt = pg_insert(SubdomainSource.__table__).values(source_records)
        stmt = stmt.on_conflict_do_nothing(
            constraint="uq_subdomain_sources_subdomain_tool_scan"
        )
        db.execute(stmt)
        db.commit()

    def bulk_insert_sources_staged(
        self, db: Session, source_records: list[dict[str, Any]]
    ) -> None:
        """COPY source rows into a temp table, then insert with DO NOTHING."""
        if not source_records:
            return
        try:
            self._bulk_insert_sources_staged(db, source_records)
        except NotImplementedError:
            db.rollback()
            self.bulk_insert_sources(db, source_records)

    def _bulk_insert_sources_staged(
        self, db: Session, source_records: list[dict[str, Any]]
    ) -> None:
        db.execute(
            text(
                """
                CREATE TEMP TABLE tmp_subdomain_source_insert (
                    id uuid NOT NULL,
                    subdomain_id uuid NOT NULL,
                    scan_run_id uuid NOT NULL,
                    tool_name varchar(128) NOT NULL,
                    created_at timestamptz NOT NULL
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
        for row in source_records:
            writer.writerow(
                [
                    row["id"],
                    row["subdomain_id"],
                    row["scan_run_id"],
                    row["tool_name"],
                    row["created_at"],
                ]
            )
        buffer.seek(0)

        self._copy_buffer_to_temp_table(db, buffer)
        db.execute(
            text(
                """
                INSERT INTO subdomain_sources (
                    id,
                    subdomain_id,
                    scan_run_id,
                    tool_name,
                    created_at
                )
                SELECT
                    id,
                    subdomain_id,
                    scan_run_id,
                    tool_name,
                    created_at
                FROM tmp_subdomain_source_insert
                ON CONFLICT ON CONSTRAINT uq_subdomain_sources_subdomain_tool_scan
                DO NOTHING
                """
            )
        )
        db.commit()

    def _copy_buffer_to_temp_table(self, db: Session, buffer: io.StringIO) -> None:
        copy_sql = (
            "COPY tmp_subdomain_source_insert ("
            "id, subdomain_id, scan_run_id, tool_name, created_at"
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

    def list_by_subdomain(
        self, db: Session, subdomain_id: uuid.UUID
    ) -> list[SubdomainSource]:
        return self.list(db, subdomain_id=subdomain_id)
