from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from database.models.js_secret import JsSecret
from repositories.base_repository import BaseRepository

_SORTABLE = {
    "severity": "severity",
    "secret_type": "secret_type",
    "host": "host",
    "confidence": "confidence",
    "first_seen": "first_seen",
    "last_seen": "last_seen",
    "created_at": "created_at",
}

# Severity ordering for "most severe first" sorts.
_SEVERITY_RANK = "CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 WHEN 'LOW' THEN 3 ELSE 4 END"


class JsSecretRepository(BaseRepository[JsSecret]):
    """Data access for the secret inventory (Phase 6.2).

    Dedup key is ``(scope_id, fingerprint)``. On conflict ``last_seen`` advances
    and ``discovery_tools`` is unioned; ``first_seen`` and the original
    ``secret_value`` are never overwritten.
    """

    def __init__(self) -> None:
        super().__init__(JsSecret)

    # ------------------------------------------------------------------
    # Filtered listing
    # ------------------------------------------------------------------

    def _apply_filters(self, stmt, search, host, secret_type, severity, tool, js_url):
        if search:
            like = f"%{search}%"
            stmt = stmt.where(or_(
                JsSecret.secret_value.ilike(like),
                JsSecret.secret_type.ilike(like),
                JsSecret.host.ilike(like),
                JsSecret.js_file_url.ilike(like),
            ))
        if host:
            stmt = stmt.where(self._domain_clause(host))
        if secret_type:
            stmt = stmt.where(JsSecret.secret_type == secret_type.upper())
        if severity:
            stmt = stmt.where(JsSecret.severity == severity.upper())
        if tool:
            stmt = stmt.where(JsSecret.discovery_tools.op("?")(tool.upper()))
        if js_url:
            stmt = stmt.where(JsSecret.js_file_url.ilike(f"%{js_url}%"))
        return stmt

    def list_secrets(
        self, db: Session, *, program_id=None, scope_id=None, host_id=None,
        js_file_id=None, host_value=None, offset=0, limit=100,
        search=None, host=None, secret_type=None, severity=None, tool=None, js_url=None,
        sort_by="severity", sort_dir="asc",
    ) -> list[JsSecret]:
        stmt = select(JsSecret)
        if program_id is not None:
            stmt = stmt.where(JsSecret.program_id == program_id)
        if scope_id is not None:
            stmt = stmt.where(JsSecret.scope_id == scope_id)
        if host_id is not None:
            stmt = stmt.where(JsSecret.host_id == host_id)
        if js_file_id is not None:
            stmt = stmt.where(JsSecret.js_file_id == js_file_id)
        if host_value is not None:
            stmt = stmt.where(JsSecret.host == host_value)
        stmt = self._apply_filters(stmt, search, host, secret_type, severity, tool, js_url)

        direction = "DESC" if sort_dir.lower() == "desc" else "ASC"
        if sort_by == "severity":
            stmt = stmt.order_by(text(f"{_SEVERITY_RANK} {direction}"), JsSecret.last_seen.desc())
        else:
            col = _SORTABLE.get(sort_by, "severity")
            stmt = stmt.order_by(text(f"{col} {direction}"))
        return list(db.scalars(stmt.offset(offset).limit(limit)).all())

    def count_secrets(
        self, db: Session, *, program_id=None, scope_id=None, host_id=None,
        js_file_id=None, host_value=None,
        search=None, host=None, secret_type=None, severity=None, tool=None, js_url=None,
    ) -> int:
        stmt = select(func.count()).select_from(JsSecret)
        if program_id is not None:
            stmt = stmt.where(JsSecret.program_id == program_id)
        if scope_id is not None:
            stmt = stmt.where(JsSecret.scope_id == scope_id)
        if host_id is not None:
            stmt = stmt.where(JsSecret.host_id == host_id)
        if js_file_id is not None:
            stmt = stmt.where(JsSecret.js_file_id == js_file_id)
        if host_value is not None:
            stmt = stmt.where(JsSecret.host == host_value)
        stmt = self._apply_filters(stmt, search, host, secret_type, severity, tool, js_url)
        return int(db.scalar(stmt) or 0)

    @staticmethod
    def _domain_clause(domain: str):
        safe = domain.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return or_(JsSecret.host == domain, JsSecret.host.like(f"%.{safe}", escape="\\"))

    # ------------------------------------------------------------------
    # Dashboard aggregates
    # ------------------------------------------------------------------

    def count_for_scope(self, db: Session, scope_id: uuid.UUID) -> int:
        return int(db.scalar(
            select(func.count()).select_from(JsSecret).where(JsSecret.scope_id == scope_id)
        ) or 0)

    def stats(self, db: Session, *, program_id=None, scope_id=None) -> dict:
        """Dashboard counters: totals by severity + by secret type."""
        base = select(JsSecret)
        if program_id is not None:
            base = base.where(JsSecret.program_id == program_id)
        if scope_id is not None:
            base = base.where(JsSecret.scope_id == scope_id)
        sub = base.subquery()

        total = int(db.scalar(select(func.count()).select_from(sub)) or 0)
        by_sev = dict(db.execute(
            select(sub.c.severity, func.count()).group_by(sub.c.severity)
        ).fetchall())
        by_type = dict(db.execute(
            select(sub.c.secret_type, func.count()).group_by(sub.c.secret_type)
            .order_by(func.count().desc())
        ).fetchall())
        return {"total": total, "by_severity": {k: int(v) for k, v in by_sev.items()},
                "by_type": {k: int(v) for k, v in by_type.items()}}

    # ------------------------------------------------------------------
    # Bulk upsert (ON CONFLICT scope_id, fingerprint) with tool-union
    # ------------------------------------------------------------------

    def bulk_upsert(self, db: Session, rows: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
        if not rows:
            return [], []
        # Deduplicate within the batch on fingerprint, merging tools.
        deduped: dict[tuple[Any, Any], dict[str, Any]] = {}
        for row in rows:
            key = (row["scope_id"], row["fingerprint"])
            if key in deduped:
                merged = set(deduped[key]["discovery_tools"]) | set(row["discovery_tools"])
                deduped[key]["discovery_tools"] = sorted(merged)
            else:
                d = dict(row)
                d["discovery_tools"] = sorted(set(row["discovery_tools"]))
                deduped[key] = d
        rows = list(deduped.values())
        return self._bulk_upsert_inline(db, rows)

    def _bulk_upsert_inline(self, db: Session, rows: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
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

        stmt = pg_insert(JsSecret.__table__).values(rows)
        merged_tools = text("""
            (SELECT COALESCE(jsonb_agg(DISTINCT t ORDER BY t), '[]'::jsonb)
             FROM jsonb_array_elements_text(
                 js_secrets.discovery_tools || excluded.discovery_tools) AS t)
        """)
        upsert = stmt.on_conflict_do_update(
            index_elements=["scope_id", "fingerprint"],
            set_={
                "last_seen": stmt.excluded.last_seen,
                "host_id": func.coalesce(JsSecret.__table__.c.host_id, stmt.excluded.host_id),
                "js_file_id": func.coalesce(JsSecret.__table__.c.js_file_id, stmt.excluded.js_file_id),
                "js_file_url": func.coalesce(JsSecret.__table__.c.js_file_url, stmt.excluded.js_file_url),
                "host": func.coalesce(JsSecret.__table__.c.host, stmt.excluded.host),
                "discovery_tools": merged_tools,
                "updated_at": func.now(),
            },
        ).returning(
            JsSecret.__table__.c.id,
            JsSecret.__table__.c.fingerprint,
            JsSecret.__table__.c.host_id,
            JsSecret.__table__.c.host,
            JsSecret.__table__.c.secret_type,
            JsSecret.__table__.c.severity,
            text("(xmax = 0) AS is_new"),
        )
        all_rows = db.execute(upsert).fetchall()
        db.commit()
        new_rows, existing_rows = [], []
        for r in all_rows:
            entry = {"id": r.id, "fingerprint": r.fingerprint, "host_id": r.host_id,
                     "host": r.host, "secret_type": r.secret_type, "severity": r.severity}
            (new_rows if r.is_new else existing_rows).append(entry)
        return new_rows, existing_rows

    def bulk_insert_sources(self, db: Session, rows: list[dict[str, Any]]) -> None:
        """Insert js_secret_sources rows ON CONFLICT DO NOTHING. {secret_id, tool_name}."""
        if not rows:
            return
        chunk = 5000
        for start in range(0, len(rows), chunk):
            db.execute(text("""
                INSERT INTO js_secret_sources (id, secret_id, tool_name, created_at)
                VALUES (gen_random_uuid(), :secret_id, :tool_name, now())
                ON CONFLICT (secret_id, tool_name) DO NOTHING
            """), rows[start:start + chunk])
        db.commit()
