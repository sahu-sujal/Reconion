from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from database.models.http_response import HttpResponse
from repositories.base_repository import BaseRepository


class HttpResponseRepository(BaseRepository[HttpResponse]):
    def __init__(self) -> None:
        super().__init__(HttpResponse)

    def list_by_scope(
        self,
        db: Session,
        scope_id: uuid.UUID,
        status_code: int | None = None,
        offset: int = 0,
        limit: int = 2000,
    ) -> list[HttpResponse]:
        stmt = (
            select(HttpResponse)
            .where(HttpResponse.scope_id == scope_id)
            .order_by(HttpResponse.url)
            .offset(offset)
            .limit(limit)
        )
        if status_code is not None:
            stmt = stmt.where(HttpResponse.status_code == status_code)
        return list(db.scalars(stmt).all())

    def list_by_host(self, db: Session, host_id: uuid.UUID) -> list[HttpResponse]:
        stmt = (
            select(HttpResponse)
            .where(HttpResponse.host_id == host_id)
            .order_by(HttpResponse.url)
        )
        return list(db.scalars(stmt).all())

    def count_by_scope(self, db: Session, scope_id: uuid.UUID) -> int:
        return int(db.scalar(
            select(func.count()).select_from(HttpResponse)
            .where(HttpResponse.scope_id == scope_id)
        ) or 0)

    def status_distribution(self, db: Session, scope_id: uuid.UUID) -> list[dict]:
        """Return [{status_code, count}] ordered by count desc."""
        rows = db.execute(
            text("""
                SELECT status_code, COUNT(*) AS cnt
                FROM http_responses
                WHERE scope_id = :scope_id
                GROUP BY status_code
                ORDER BY cnt DESC
            """),
            {"scope_id": str(scope_id)},
        ).fetchall()
        return [{"status_code": r.status_code, "count": r.cnt} for r in rows]

    def bulk_upsert(
        self,
        db: Session,
        rows: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """Upsert http_responses ON CONFLICT (host_id, url).

        Returns (inserted_count, updated_count).
        """
        if not rows:
            return 0, 0

        # Deduplicate by the conflict key (host_id, url): Postgres rejects an
        # ON CONFLICT DO UPDATE that touches the same target row twice in one
        # statement (CardinalityViolation). httpx can emit several records that
        # map to the same (host_id, url) — e.g. probing multiple ports or
        # following redirects — so keep the last occurrence (latest wins).
        deduped: dict[tuple[Any, Any], dict[str, Any]] = {}
        for row in rows:
            deduped[(row["host_id"], row["url"])] = row
        rows = list(deduped.values())

        # Chunk to stay under Postgres' 65535 bind-parameter limit
        # (13 params/row → ~5000 rows max; use 4000 for headroom).
        chunk_size = 4000
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
                f"(:id_{i}, :program_id_{i}, :scope_id_{i}, :host_id_{i},"
                f" :url_{i}, :status_code_{i}, :title_{i}, :content_length_{i},"
                f" :server_{i}, CAST(:technologies_{i} AS jsonb), :response_time_{i},"
                f" :created_at_{i}, :updated_at_{i})"
            )
            flat_params[f"id_{i}"] = row["id"]
            flat_params[f"program_id_{i}"] = row["program_id"]
            flat_params[f"scope_id_{i}"] = row["scope_id"]
            flat_params[f"host_id_{i}"] = row["host_id"]
            flat_params[f"url_{i}"] = row["url"]
            flat_params[f"status_code_{i}"] = row.get("status_code")
            flat_params[f"title_{i}"] = row.get("title")
            flat_params[f"content_length_{i}"] = row.get("content_length")
            flat_params[f"server_{i}"] = row.get("server")
            flat_params[f"technologies_{i}"] = row.get("technologies")
            flat_params[f"response_time_{i}"] = row.get("response_time")
            flat_params[f"created_at_{i}"] = row["created_at"]
            flat_params[f"updated_at_{i}"] = row["updated_at"]

        result = db.execute(
            text(
                f"""
                INSERT INTO http_responses (
                    id, program_id, scope_id, host_id,
                    url, status_code, title, content_length,
                    server, technologies, response_time,
                    created_at, updated_at
                )
                VALUES {", ".join(placeholders)}
                ON CONFLICT (host_id, url)
                DO UPDATE SET
                    status_code    = EXCLUDED.status_code,
                    title          = EXCLUDED.title,
                    content_length = EXCLUDED.content_length,
                    server         = EXCLUDED.server,
                    technologies   = EXCLUDED.technologies,
                    response_time  = EXCLUDED.response_time,
                    updated_at     = now()
                RETURNING (xmax = 0) AS is_new
                """
            ),
            flat_params,
        )
        all_rows = result.fetchall()
        db.commit()

        inserted = sum(1 for r in all_rows if r.is_new)
        return inserted, len(all_rows) - inserted
