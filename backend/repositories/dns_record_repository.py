from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, joinedload

from database.models.dns_record import DnsRecord
from repositories.base_repository import BaseRepository


class DnsRecordRepository(BaseRepository[DnsRecord]):
    def __init__(self) -> None:
        super().__init__(DnsRecord)

    def list_by_scope(
        self,
        db: Session,
        scope_id: uuid.UUID,
        record_type: str | None = None,
        offset: int = 0,
        limit: int = 2000,
    ) -> list[DnsRecord]:
        stmt = (
            select(DnsRecord)
            .options(joinedload(DnsRecord.subdomain))
            .where(DnsRecord.scope_id == scope_id)
            .order_by(DnsRecord.record_type, DnsRecord.record_value)
            .offset(offset)
            .limit(limit)
        )
        if record_type:
            stmt = stmt.where(DnsRecord.record_type == record_type.upper())
        return list(db.scalars(stmt).unique().all())

    def list_by_host(
        self,
        db: Session,
        host_id: uuid.UUID,
    ) -> list[DnsRecord]:
        stmt = (
            select(DnsRecord)
            .where(DnsRecord.host_id == host_id)
            .order_by(DnsRecord.record_type, DnsRecord.record_value)
        )
        return list(db.scalars(stmt).all())

    def count_by_scope(self, db: Session, scope_id: uuid.UUID) -> int:
        return int(db.scalar(
            select(func.count()).select_from(DnsRecord).where(DnsRecord.scope_id == scope_id)
        ) or 0)

    def bulk_upsert(
        self,
        db: Session,
        rows: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """Upsert dns_records ON CONFLICT (host_id, record_type, record_value).

        Returns (inserted_count, updated_count).
        """
        if not rows:
            return 0, 0

        # Chunk to stay under Postgres' 65535 bind-parameter limit
        # (10 params/row → ~6500 rows max; use 5000 for headroom). Without
        # this, large scopes overflow the limit and the statement errors.
        chunk_size = 5000
        if len(rows) > chunk_size:
            total_inserted = total_updated = 0
            for start in range(0, len(rows), chunk_size):
                ins, upd = self.bulk_upsert(db, rows[start:start + chunk_size])
                total_inserted += ins
                total_updated += upd
            return total_inserted, total_updated

        placeholders = []
        flat_params: dict[str, Any] = {}
        for i, row in enumerate(rows):
            placeholders.append(
                f"(:id_{i}, :program_id_{i}, :scope_id_{i}, :host_id_{i}, :subdomain_id_{i},"
                f" :record_type_{i}, :record_value_{i}, :ttl_{i},"
                f" :created_at_{i}, :updated_at_{i})"
            )
            flat_params[f"id_{i}"] = row["id"]
            flat_params[f"program_id_{i}"] = row["program_id"]
            flat_params[f"scope_id_{i}"] = row["scope_id"]
            flat_params[f"host_id_{i}"] = row["host_id"]
            flat_params[f"subdomain_id_{i}"] = row.get("subdomain_id")
            flat_params[f"record_type_{i}"] = row["record_type"]
            flat_params[f"record_value_{i}"] = row["record_value"]
            flat_params[f"ttl_{i}"] = row.get("ttl")
            flat_params[f"created_at_{i}"] = row["created_at"]
            flat_params[f"updated_at_{i}"] = row["updated_at"]

        result = db.execute(
            text(
                f"""
                INSERT INTO dns_records (
                    id, program_id, scope_id, host_id, subdomain_id,
                    record_type, record_value, ttl,
                    created_at, updated_at
                )
                VALUES {", ".join(placeholders)}
                ON CONFLICT (host_id, record_type, record_value)
                DO UPDATE SET
                    ttl          = EXCLUDED.ttl,
                    subdomain_id = COALESCE(EXCLUDED.subdomain_id, dns_records.subdomain_id),
                    updated_at   = now()
                RETURNING (xmax = 0) AS is_new
                """
            ),
            flat_params,
        )
        all_rows = result.fetchall()
        db.commit()

        inserted = sum(1 for r in all_rows if r.is_new)
        updated = len(all_rows) - inserted
        return inserted, updated
