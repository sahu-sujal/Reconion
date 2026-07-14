from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from database.models.screenshot import Screenshot
from repositories.base_repository import BaseRepository


class ScreenshotRepository(BaseRepository[Screenshot]):
    def __init__(self) -> None:
        super().__init__(Screenshot)

    def list_by_scope(
        self,
        db: Session,
        scope_id: uuid.UUID,
        offset: int = 0,
        limit: int = 5000,
    ) -> list[Screenshot]:
        stmt = (
            select(Screenshot)
            .where(Screenshot.scope_id == scope_id)
            .order_by(Screenshot.url)
            .offset(offset)
            .limit(limit)
        )
        return list(db.scalars(stmt).all())

    def list_by_host(self, db: Session, host_id: uuid.UUID) -> list[Screenshot]:
        stmt = (
            select(Screenshot)
            .where(Screenshot.host_id == host_id)
            .order_by(Screenshot.url)
        )
        return list(db.scalars(stmt).all())

    def count_by_scope(self, db: Session, scope_id: uuid.UUID) -> int:
        return int(db.scalar(
            select(func.count()).select_from(Screenshot)
            .where(Screenshot.scope_id == scope_id)
        ) or 0)

    def bulk_upsert(
        self,
        db: Session,
        rows: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """Upsert screenshots ON CONFLICT (host_id, url).

        Returns (inserted_count, updated_count).
        """
        if not rows:
            return 0, 0

        # Dedupe on the conflict key — the same (host_id, url) twice in one
        # statement would raise a CardinalityViolation.
        deduped: dict[tuple[Any, Any], dict[str, Any]] = {}
        for row in rows:
            deduped[(row["host_id"], row["url"])] = row
        rows = list(deduped.values())

        chunk_size = 4000
        if len(rows) > chunk_size:
            total_ins = total_upd = 0
            for start in range(0, len(rows), chunk_size):
                ins, upd = self.bulk_upsert(db, rows[start:start + chunk_size])
                total_ins += ins
                total_upd += upd
            return total_ins, total_upd

        placeholders = []
        flat: dict[str, Any] = {}
        for i, row in enumerate(rows):
            placeholders.append(
                f"(:id_{i}, :program_id_{i}, :scope_id_{i}, :host_id_{i},"
                f" :url_{i}, :final_url_{i}, :title_{i}, :status_code_{i},"
                f" :file_name_{i}, :file_path_{i}, :failed_{i}, :failed_reason_{i},"
                f" :captured_at_{i}, :created_at_{i}, :updated_at_{i})"
            )
            flat[f"id_{i}"] = row["id"]
            flat[f"program_id_{i}"] = row["program_id"]
            flat[f"scope_id_{i}"] = row["scope_id"]
            flat[f"host_id_{i}"] = row["host_id"]
            flat[f"url_{i}"] = row["url"]
            flat[f"final_url_{i}"] = row.get("final_url")
            flat[f"title_{i}"] = row.get("title")
            flat[f"status_code_{i}"] = row.get("status_code")
            flat[f"file_name_{i}"] = row.get("file_name")
            flat[f"file_path_{i}"] = row.get("file_path")
            flat[f"failed_{i}"] = bool(row.get("failed"))
            flat[f"failed_reason_{i}"] = row.get("failed_reason")
            flat[f"captured_at_{i}"] = row.get("captured_at")
            flat[f"created_at_{i}"] = row["created_at"]
            flat[f"updated_at_{i}"] = row["updated_at"]

        result = db.execute(
            text(
                f"""
                INSERT INTO screenshots (
                    id, program_id, scope_id, host_id,
                    url, final_url, title, status_code,
                    file_name, file_path, failed, failed_reason,
                    captured_at, created_at, updated_at
                )
                VALUES {", ".join(placeholders)}
                ON CONFLICT (host_id, url)
                DO UPDATE SET
                    final_url     = EXCLUDED.final_url,
                    title         = EXCLUDED.title,
                    status_code   = EXCLUDED.status_code,
                    file_name     = EXCLUDED.file_name,
                    file_path     = EXCLUDED.file_path,
                    failed        = EXCLUDED.failed,
                    failed_reason = EXCLUDED.failed_reason,
                    captured_at   = EXCLUDED.captured_at,
                    updated_at    = now()
                RETURNING (xmax = 0) AS is_new
                """
            ),
            flat,
        )
        all_rows = result.fetchall()
        db.commit()
        inserted = sum(1 for r in all_rows if r.is_new)
        return inserted, len(all_rows) - inserted
