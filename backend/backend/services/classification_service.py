"""Asset Classification Service — Phase 6.3.

Runs the :mod:`tools.common.asset_classifier` engine over every URL, endpoint and
JS file in a scope and writes the classification columns back **in place** (no new
rows, no duplication). Purely local — never makes a network request.

Invoked as a pipeline step after URL + endpoint collection and before any active
analysis (Parameter Discovery, GF, Vulnerability Scanning), so those phases can
select the right asset subset (e.g. ``is_api`` for parameter discovery).

Idempotent: safe to re-run on a rescan — it simply recomputes the same columns.
Streams in batches so a scope with hundreds of thousands of rows stays within
constant memory.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import bindparam
from sqlalchemy.orm import Session

from database.models.endpoint import Endpoint
from database.models.js_file import JsFile
from database.models.url import URL
from tools.common.asset_classifier import JAVASCRIPT, classify

logger = logging.getLogger(__name__)

_BATCH = 5_000


@dataclass
class ClassificationMetrics:
    urls_classified: int = 0
    endpoints_classified: int = 0
    js_classified: int = 0
    by_category: dict[str, int] = field(default_factory=dict)

    def _bump(self, category: str) -> None:
        self.by_category[category] = self.by_category.get(category, 0) + 1

    @property
    def total(self) -> int:
        return self.urls_classified + self.endpoints_classified + self.js_classified


class ClassificationService:
    """Classify all content assets in a scope, writing columns in place."""

    def classify_scope(self, db: Session, scope_id: uuid.UUID) -> ClassificationMetrics:
        metrics = ClassificationMetrics()
        self._classify_urls(db, scope_id, metrics)
        self._classify_endpoints(db, scope_id, metrics)
        self._classify_js(db, scope_id, metrics)
        db.commit()
        logger.info(
            "Asset classification scope=%s urls=%d endpoints=%d js=%d categories=%s",
            scope_id, metrics.urls_classified, metrics.endpoints_classified,
            metrics.js_classified, metrics.by_category,
        )
        return metrics

    # ------------------------------------------------------------------ #

    def _classify_urls(self, db: Session, scope_id: uuid.UUID, m: ClassificationMetrics) -> None:
        stmt = (
            db.query(URL.id, URL.normalized_url, URL.host, URL.path, URL.query, URL.extension)
            .filter(URL.scope_id == scope_id)
            .yield_per(_BATCH)
        )
        updates: list[dict] = []
        for row in stmt:
            c = classify(
                row.normalized_url, host=row.host, path=row.path,
                query=row.query, extension=row.extension,
            )
            cols = c.as_columns()
            updates.append({"_id": row.id, **cols})
            m._bump(c.asset_category)
            m.urls_classified += 1
            if len(updates) >= _BATCH:
                self._flush(db, URL, updates)
                updates = []
        self._flush(db, URL, updates)

    def _classify_endpoints(self, db: Session, scope_id: uuid.UUID, m: ClassificationMetrics) -> None:
        stmt = (
            db.query(
                Endpoint.id, Endpoint.normalized_url, Endpoint.host,
                Endpoint.path, Endpoint.query, Endpoint.extension,
            )
            .filter(Endpoint.scope_id == scope_id)
            .yield_per(_BATCH)
        )
        updates: list[dict] = []
        for row in stmt:
            c = classify(
                row.normalized_url, host=row.host, path=row.path,
                query=row.query, extension=row.extension,
            )
            cols = c.as_columns()
            # Endpoints track a parameter_count too (from the query string).
            cols["parameter_count"] = _count_params(row.query, row.normalized_url)
            updates.append({"_id": row.id, **cols})
            m._bump(c.asset_category)
            m.endpoints_classified += 1
            if len(updates) >= _BATCH:
                self._flush(db, Endpoint, updates)
                updates = []
        self._flush(db, Endpoint, updates)

    def _classify_js(self, db: Session, scope_id: uuid.UUID, m: ClassificationMetrics) -> None:
        # JS files are always JAVASCRIPT — classify by the constant so the boolean
        # traits stay consistent with the engine (is_static, is_script).
        stmt = (
            db.query(JsFile.id, JsFile.url, JsFile.extension)
            .filter(JsFile.scope_id == scope_id)
            .yield_per(_BATCH)
        )
        updates: list[dict] = []
        for row in stmt:
            c = classify(row.url, extension=row.extension, is_js_file=True)
            cols = c.as_columns()
            # JS view row has no has_parameters/parameter_count columns.
            cols.pop("has_parameters", None)
            updates.append({"_id": row.id, **cols})
            m._bump(JAVASCRIPT)
            m.js_classified += 1
            if len(updates) >= _BATCH:
                self._flush(db, JsFile, updates)
                updates = []
        self._flush(db, JsFile, updates)

    @staticmethod
    def _flush(db: Session, model, updates: list[dict]) -> None:
        if not updates:
            return
        # Use the Core table UPDATE (not ORM bulk-by-PK) so we can key the WHERE on
        # a distinctly-named bind param and executemany over the batch.
        table = model.__table__
        value_cols = [k for k in updates[0] if k != "_id"]
        stmt = (
            table.update()
            .where(table.c.id == bindparam("b_id"))
            .values({c: bindparam(c) for c in value_cols})
        )
        params = [{"b_id": u["_id"], **{c: u[c] for c in value_cols}} for u in updates]
        db.execute(stmt, params)


def _count_params(query: str | None, url: str) -> int:
    q = query
    if not q and "?" in url:
        q = url.split("?", 1)[1]
    if not q:
        return 0
    return sum(1 for part in q.split("&") if part and "=" in part)
