"""Unified JavaScript-URL source for secret discovery — Phase 6.2 extension.

Secret discovery originally scanned only the ``js_files`` table. In practice a
scope's JavaScript surface is larger: many ``.js`` URLs and endpoints are stored
in ``urls`` / ``endpoints`` and are already classified as ``JAVASCRIPT`` by the
Asset Classification Engine (Phase 6.3), yet never became ``js_files`` rows.

This repository is the equivalent of the manual recon one-liner::

    cat allurls.txt | grep '\\.js$' | httpx (js content-type) | curl | grep secrets

but sourced from the **classified inventory**: it streams the distinct set of JS
URLs across all three tables — ``js_files`` + JS-classified ``urls`` +
JS-classified ``endpoints`` — deduplicated by URL, with keyset pagination so a
scope with hundreds of thousands of JS references stays in constant memory.

The secret worker downloads + scans each URL (SecretFinder / Mantra / Nuclei),
so the "is it live / is it really JS" check the one-liner does with httpx is
handled by the download step (dead/non-JS URLs simply yield nothing).
"""
from __future__ import annotations

import uuid
from typing import Iterator

from sqlalchemy import text
from sqlalchemy.orm import Session


class JsSourceRepository:
    """Stream the scope's full JavaScript-URL surface for secret scanning."""

    # A url/endpoint row counts as JavaScript when the classifier tagged it so —
    # asset_category = 'JAVASCRIPT' (covers .js/.mjs/.cjs by extension) — kept in
    # one place so the JS predicate is defined once.
    _JS_PREDICATE = "asset_category = 'JAVASCRIPT'"

    def count_scope_js_urls(self, db: Session, scope_id: uuid.UUID) -> int:
        """Count distinct JS URLs across js_files + urls + endpoints."""
        sql = f"""
            SELECT count(*) FROM (
                SELECT url AS u FROM js_files WHERE scope_id = :scope_id
                UNION
                SELECT normalized_url AS u FROM urls
                    WHERE scope_id = :scope_id AND {self._JS_PREDICATE}
                UNION
                SELECT normalized_url AS u FROM endpoints
                    WHERE scope_id = :scope_id AND {self._JS_PREDICATE}
            ) d
        """
        return int(db.execute(text(sql), {"scope_id": str(scope_id)}).scalar() or 0)

    def iter_scope_js_urls(
        self,
        db: Session,
        scope_id: uuid.UUID,
        *,
        batch_size: int = 300,
        after_url: str | None = None,
    ) -> Iterator[tuple[str, uuid.UUID | None]]:
        """Yield ``(js_url, host_id)`` for every distinct JS URL in the scope.

        Deduplicated by URL across the three sources. ``host_id`` is the best
        available host id for the URL (from whichever source provides one).
        Keyset-paginated on the URL string (stable, commit-safe) so the worker
        can page without a server-side cursor. ``after_url`` resumes mid-way.
        """
        cursor = after_url
        while True:
            params = {"scope_id": str(scope_id), "limit": batch_size}
            cursor_clause = ""
            if cursor is not None:
                cursor_clause = "AND d.u > :cursor"
                params["cursor"] = cursor
            sql = f"""
                SELECT d.u AS url, max(d.host_id::text) AS host_id
                FROM (
                    SELECT url AS u, host_id FROM js_files
                        WHERE scope_id = :scope_id
                    UNION ALL
                    SELECT normalized_url AS u, host_id FROM urls
                        WHERE scope_id = :scope_id AND {self._JS_PREDICATE}
                    UNION ALL
                    SELECT normalized_url AS u, host_id FROM endpoints
                        WHERE scope_id = :scope_id AND {self._JS_PREDICATE}
                ) d
                WHERE d.u IS NOT NULL {cursor_clause}
                GROUP BY d.u
                ORDER BY d.u
                LIMIT :limit
            """
            rows = db.execute(text(sql), params).mappings().all()
            if not rows:
                return
            for r in rows:
                hid = uuid.UUID(r["host_id"]) if r["host_id"] else None
                yield r["url"], hid
            cursor = rows[-1]["url"]
            if len(rows) < batch_size:
                return
