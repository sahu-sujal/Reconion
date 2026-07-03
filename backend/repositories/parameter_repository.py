"""Parameter Inventory repository — Phase 6.4.

Data access for the centralized ``parameters`` table. Deduplication key is
``(scope_id, asset_id, parameter_name)``: the same parameter rediscovered on one
asset by another tool upserts onto one row and *unions* ``discovery_tools``;
``first_seen`` is never overwritten. Bulk upsert + tool-union mirror the endpoint
and secret repositories so the worker stays uniform.

Listing supports search (name / asset URL / host), pagination, sorting, and
filtering by host, discovery tool, and parameter type — the search facets the
spec requires.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from database.models.parameter import Parameter
from repositories.base_repository import BaseRepository

# Sortable columns exposed to the API (whitelist — never interpolate raw input).
_SORTABLE = {
    "parameter_name": "parameter_name",
    "parameter_type": "parameter_type",
    "host": "host",
    "asset_url": "asset_url",
    "first_seen": "first_seen",
    "last_seen": "last_seen",
    "created_at": "created_at",
}


class ParameterRepository(BaseRepository[Parameter]):
    """Data access for the unified parameter inventory (Phase 6.4)."""

    def __init__(self) -> None:
        super().__init__(Parameter)

    # ------------------------------------------------------------------
    # Filtered listing (pagination + search + sorting + filters)
    # ------------------------------------------------------------------

    def _apply_filters(
        self,
        stmt,
        search: str | None,
        host: str | None,
        tool: str | None,
        parameter_type: str | None,
        asset_type: str | None,
    ):
        if search:
            like = f"%{search}%"
            stmt = stmt.where(or_(
                Parameter.parameter_name.ilike(like),
                Parameter.asset_url.ilike(like),
                Parameter.host.ilike(like),
            ))
        if host:
            stmt = stmt.where(self._domain_clause(host))
        if tool:
            stmt = stmt.where(Parameter.discovery_tools.op("?")(tool.upper()))
        if parameter_type:
            stmt = stmt.where(Parameter.parameter_type == parameter_type.upper())
        if asset_type:
            stmt = stmt.where(Parameter.asset_type == asset_type.upper())
        return stmt

    def list_parameters(
        self,
        db: Session,
        *,
        program_id: uuid.UUID | None = None,
        scope_id: uuid.UUID | None = None,
        host_id: uuid.UUID | None = None,
        asset_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 100,
        search: str | None = None,
        host: str | None = None,
        tool: str | None = None,
        parameter_type: str | None = None,
        asset_type: str | None = None,
        sort_by: str = "parameter_name",
        sort_dir: str = "asc",
    ) -> list[Parameter]:
        stmt = select(Parameter)
        if program_id is not None:
            stmt = stmt.where(Parameter.program_id == program_id)
        if scope_id is not None:
            stmt = stmt.where(Parameter.scope_id == scope_id)
        if host_id is not None:
            stmt = stmt.where(Parameter.host_id == host_id)
        if asset_id is not None:
            stmt = stmt.where(Parameter.asset_id == asset_id)
        stmt = self._apply_filters(stmt, search, host, tool, parameter_type, asset_type)

        column = _SORTABLE.get(sort_by, "parameter_name")
        direction = "DESC" if sort_dir.lower() == "desc" else "ASC"
        stmt = stmt.order_by(text(f"{column} {direction}")).offset(offset).limit(limit)
        return list(db.scalars(stmt).all())

    def count_parameters(
        self,
        db: Session,
        *,
        program_id: uuid.UUID | None = None,
        scope_id: uuid.UUID | None = None,
        host_id: uuid.UUID | None = None,
        asset_id: uuid.UUID | None = None,
        search: str | None = None,
        host: str | None = None,
        tool: str | None = None,
        parameter_type: str | None = None,
        asset_type: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(Parameter)
        if program_id is not None:
            stmt = stmt.where(Parameter.program_id == program_id)
        if scope_id is not None:
            stmt = stmt.where(Parameter.scope_id == scope_id)
        if host_id is not None:
            stmt = stmt.where(Parameter.host_id == host_id)
        if asset_id is not None:
            stmt = stmt.where(Parameter.asset_id == asset_id)
        stmt = self._apply_filters(stmt, search, host, tool, parameter_type, asset_type)
        return int(db.scalar(stmt) or 0)

    @staticmethod
    def _domain_clause(domain: str):
        safe = domain.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return or_(Parameter.host == domain, Parameter.host.like(f"%.{safe}", escape="\\"))

    # ------------------------------------------------------------------
    # Aggregates + dashboard stats
    # ------------------------------------------------------------------

    def count_for_scope(self, db: Session, scope_id: uuid.UUID) -> int:
        return int(db.scalar(
            select(func.count()).select_from(Parameter).where(Parameter.scope_id == scope_id)
        ) or 0)

    def count_for_asset(self, db: Session, scope_id: uuid.UUID, asset_id: uuid.UUID) -> int:
        return int(db.scalar(
            select(func.count()).select_from(Parameter).where(
                Parameter.scope_id == scope_id, Parameter.asset_id == asset_id
            )
        ) or 0)

    def new_parameters_since(self, db: Session, scope_id: uuid.UUID, since) -> int:
        return int(db.scalar(
            select(func.count()).select_from(Parameter).where(
                Parameter.scope_id == scope_id, Parameter.first_seen >= since
            )
        ) or 0)

    def stats(self, db: Session, *, program_id=None, scope_id=None) -> dict:
        """Dashboard counters: total, unique names, by-type, most-common names."""
        base = select(Parameter)
        if program_id is not None:
            base = base.where(Parameter.program_id == program_id)
        if scope_id is not None:
            base = base.where(Parameter.scope_id == scope_id)
        sub = base.subquery()

        total = int(db.scalar(select(func.count()).select_from(sub)) or 0)
        unique_names = int(
            db.scalar(select(func.count(func.distinct(sub.c.parameter_name)))) or 0
        )
        by_type = dict(db.execute(
            select(sub.c.parameter_type, func.count())
            .group_by(sub.c.parameter_type)
            .order_by(func.count().desc())
        ).fetchall())
        # Most common parameter names (top 20) — powers the dashboard widget.
        most_common = [
            {"name": r[0], "count": int(r[1])}
            for r in db.execute(
                select(sub.c.parameter_name, func.count())
                .group_by(sub.c.parameter_name)
                .order_by(func.count().desc())
                .limit(20)
            ).fetchall()
        ]
        return {
            "total": total,
            "unique_parameters": unique_names,
            "by_type": {k: int(v) for k, v in by_type.items()},
            "most_common": most_common,
        }

    def tool_counts(self, db: Session, *, program_id=None, scope_id=None) -> dict[str, int]:
        """Count parameters attributed to each discovery tool (JSONB membership)."""
        clauses = []
        params: dict[str, Any] = {}
        if program_id is not None:
            clauses.append("program_id = :program_id")
            params["program_id"] = str(program_id)
        if scope_id is not None:
            clauses.append("scope_id = :scope_id")
            params["scope_id"] = str(scope_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            "SELECT t AS tool, count(*) AS n FROM parameters, "
            "jsonb_array_elements_text(discovery_tools) AS t"
            f"{where} GROUP BY t"
        )
        return {r.tool: int(r.n) for r in db.execute(text(sql), params)}

    # ------------------------------------------------------------------
    # Bulk upsert (ON CONFLICT scope_id, asset_id, parameter_name)
    # ------------------------------------------------------------------

    def bulk_upsert(self, db: Session, rows: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
        """Upsert parameter rows; union ``discovery_tools`` on conflict.

        Returns ``(new_rows, existing_rows)`` where each element carries the
        fields the worker needs for counters + per-tool source attribution.
        """
        if not rows:
            return [], []
        # Deduplicate within the batch on the conflict key, merging tools so a
        # single ON CONFLICT statement never touches a row twice.
        deduped: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
        for row in rows:
            key = (row["scope_id"], row["asset_id"], row["parameter_name"])
            if key in deduped:
                merged = set(deduped[key]["discovery_tools"]) | set(row["discovery_tools"])
                deduped[key]["discovery_tools"] = sorted(merged)
            else:
                d = dict(row)
                d["discovery_tools"] = sorted(set(row["discovery_tools"]))
                deduped[key] = d
        rows = list(deduped.values())
        return self._bulk_upsert_inline(db, rows)

    def _bulk_upsert_inline(
        self, db: Session, rows: list[dict[str, Any]]
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

        stmt = pg_insert(Parameter.__table__).values(rows)
        merged_tools = text("""
            (SELECT COALESCE(jsonb_agg(DISTINCT t ORDER BY t), '[]'::jsonb)
             FROM jsonb_array_elements_text(
                 parameters.discovery_tools || excluded.discovery_tools) AS t)
        """)
        upsert = stmt.on_conflict_do_update(
            index_elements=["scope_id", "asset_id", "parameter_name"],
            set_={
                "last_seen": stmt.excluded.last_seen,
                "host_id": func.coalesce(Parameter.__table__.c.host_id, stmt.excluded.host_id),
                "host": func.coalesce(Parameter.__table__.c.host, stmt.excluded.host),
                "discovery_tools": merged_tools,
                "updated_at": func.now(),
            },
        ).returning(
            Parameter.__table__.c.id,
            Parameter.__table__.c.parameter_name,
            Parameter.__table__.c.asset_id,
            Parameter.__table__.c.host_id,
            Parameter.__table__.c.host,
            text("(xmax = 0) AS is_new"),
        )
        all_rows = db.execute(upsert).fetchall()
        db.commit()
        new_rows, existing_rows = [], []
        for r in all_rows:
            entry = {
                "id": r.id, "parameter_name": r.parameter_name, "asset_id": r.asset_id,
                "host_id": r.host_id, "host": r.host,
            }
            (new_rows if r.is_new else existing_rows).append(entry)
        return new_rows, existing_rows

    def bulk_insert_sources(self, db: Session, rows: list[dict[str, Any]]) -> None:
        """Insert parameter_sources rows ON CONFLICT DO NOTHING. {parameter_id, tool_name}."""
        if not rows:
            return
        chunk = 5000
        for start in range(0, len(rows), chunk):
            db.execute(text("""
                INSERT INTO parameter_sources (id, parameter_id, tool_name, created_at)
                VALUES (gen_random_uuid(), :parameter_id, :tool_name, now())
                ON CONFLICT (parameter_id, tool_name) DO NOTHING
            """), rows[start:start + chunk])
        db.commit()

    # ------------------------------------------------------------------
    # Per-asset parameter_count maintenance (urls / endpoints)
    # ------------------------------------------------------------------

    def bulk_set_asset_parameter_counts(
        self, db: Session, table: str, counts: dict[uuid.UUID, int]
    ) -> None:
        """Set ``parameter_count`` on the origin asset rows (urls / endpoints).

        *table* must be ``"urls"`` or ``"endpoints"`` (whitelisted — never raw
        input). Counts are absolute (recomputed for the affected assets), so
        re-runs stay correct and idempotent.
        """
        if table not in ("urls", "endpoints"):
            raise ValueError(f"unsupported asset table: {table!r}")
        deltas = {aid: c for aid, c in counts.items() if aid}
        if not deltas:
            return
        rows = list(deltas.items())
        chunk_size = 5000
        for start in range(0, len(rows), chunk_size):
            chunk = rows[start:start + chunk_size]
            placeholders = []
            flat: dict[str, Any] = {}
            for i, (aid, count) in enumerate(chunk):
                if i == 0:
                    placeholders.append(f"(CAST(:id_{i} AS uuid), CAST(:c_{i} AS integer))")
                else:
                    placeholders.append(f"(:id_{i}, :c_{i})")
                flat[f"id_{i}"] = str(aid)
                flat[f"c_{i}"] = int(count)
            db.execute(
                text(f"""
                    UPDATE {table} AS a SET
                        parameter_count = v.c,
                        has_parameters = (v.c > 0),
                        updated_at = now()
                    FROM (VALUES {", ".join(placeholders)}) AS v(id, c)
                    WHERE a.id = v.id
                """),
                flat,
            )
        db.commit()
