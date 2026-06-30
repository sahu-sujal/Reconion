from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from database.models.asset import Asset
from repositories.base_repository import BaseRepository


class AssetRepository(BaseRepository[Asset]):
    def __init__(self) -> None:
        super().__init__(Asset)

    def bulk_upsert_subdomains(
        self,
        db: Session,
        rows: list[dict[str, Any]],
    ) -> dict[str, uuid.UUID]:
        """Upsert Asset rows (type=SUBDOMAIN) and return {asset_value: asset_id}.

        ON CONFLICT (program_id, scope_id, asset_value) updates last_seen only.
        """
        if not rows:
            return {}

        # Build a single INSERT … VALUES (…),(…),… so RETURNING works.
        # executemany (passing a list to text()) closes the cursor before RETURNING
        # rows can be fetched — a single-statement execute avoids that limitation.
        placeholders = []
        flat_params: dict[str, Any] = {}
        for i, row in enumerate(rows):
            placeholders.append(
                f"(:id_{i}, :program_id_{i}, :scope_id_{i}, 'SUBDOMAIN', :asset_value_{i},"
                f" :source_{i}, 'active', :first_seen_{i}, :last_seen_{i},"
                f" :created_at_{i}, :updated_at_{i})"
            )
            flat_params[f"id_{i}"] = row["id"]
            flat_params[f"program_id_{i}"] = row["program_id"]
            flat_params[f"scope_id_{i}"] = row["scope_id"]
            flat_params[f"asset_value_{i}"] = row["asset_value"]
            flat_params[f"source_{i}"] = row.get("source")
            flat_params[f"first_seen_{i}"] = row["first_seen"]
            flat_params[f"last_seen_{i}"] = row["last_seen"]
            flat_params[f"created_at_{i}"] = row["created_at"]
            flat_params[f"updated_at_{i}"] = row["updated_at"]

        sql = text(
            f"""
            INSERT INTO assets (
                id, program_id, scope_id, asset_type, asset_value,
                source, status, first_seen, last_seen, created_at, updated_at
            )
            VALUES {", ".join(placeholders)}
            ON CONFLICT (program_id, scope_id, asset_value) DO UPDATE
            SET last_seen = EXCLUDED.last_seen,
                updated_at = now()
            RETURNING id, asset_value
            """
        )
        result = db.execute(sql, flat_params)
        rows_returned = result.fetchall()
        db.commit()
        return {r.asset_value: r.id for r in rows_returned}
