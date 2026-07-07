"""Dynamic-asset routing repository — Phase 6.4.

The Asset Classification Engine (Phase 6.3) is the routing layer for parameter
discovery: this repository streams **only** the assets that are safe/worthwhile
to probe for parameters and never the rest.

A row qualifies when it is dynamic — ``is_dynamic`` OR ``is_api`` — which covers
APIs, dynamic pages, authentication, administration, upload, download and any
"unknown dynamic" asset (an unclassified URL that carries query parameters is
marked dynamic by the classifier). Static resources — CSS, JavaScript, images,
fonts, video, audio, archives, documents, source maps — have neither trait set
and are therefore never returned.

Assets are streamed with **keyset pagination** (id-ordered) so a scope with
millions of rows is processed in constant memory, matching the Phase 6.1/6.2
worker model. Both ``urls`` and ``endpoints`` are sources; each yielded item
records which table it came from so the worker can attribute parameters to the
right asset and maintain per-asset counts.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterator

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(slots=True)
class DynamicAsset:
    """One dynamic asset to route into parameter discovery."""

    asset_id: uuid.UUID
    asset_type: str           # "URL" | "ENDPOINT"
    url: str                  # absolute/normalized URL to probe
    host: str | None
    host_id: uuid.UUID | None


class DynamicAssetRepository:
    """Stream the parameter-discovery target subset of the inventory for a scope.

    Routing policy (denylist): run parameter discovery on **every non-static**
    URL/endpoint — skip only static resources that can't accept parameters.
    Excluded by extension: js, css, json, pdf, txt (plus the obvious static/binary
    kinds — images, fonts, media, archives, maps). Excluded by category: the
    static-file categories (JAVASCRIPT, STYLESHEET, IMAGE, FONT, VIDEO, AUDIO,
    DOCUMENT, ARCHIVE). Everything else — web pages, APIs, dynamic pages,
    auth/admin, documentation, unknown, extension-less routes — is a target.
    """

    # Extensions that never accept meaningful HTTP parameters — skip them.
    _EXCLUDED_EXTENSIONS = (
        # Explicitly requested exclusions.
        "js", "mjs", "cjs", "css", "json", "pdf", "txt",
        # Other clearly-static / binary types (no parameter surface).
        "map", "png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "bmp", "avif",
        "tiff", "woff", "woff2", "ttf", "otf", "eot",
        "mp4", "webm", "mov", "avi", "mkv", "m3u8",
        "mp3", "wav", "ogg", "flac", "aac", "m4a",
        "zip", "rar", "tar", "gz", "tgz", "7z", "bz2", "xz",
    )

    # Categories whose assets are static files — never parameter targets.
    _EXCLUDED_CATEGORIES = (
        "JAVASCRIPT", "STYLESHEET", "IMAGE", "FONT", "VIDEO", "AUDIO", "ARCHIVE",
    )

    def _target_predicate(self, alias: str) -> str:
        """Denylist predicate: keep everything that is NOT a static resource."""
        exts = ", ".join(f"'{e}'" for e in self._EXCLUDED_EXTENSIONS)
        cats = ", ".join(f"'{c}'" for c in self._EXCLUDED_CATEGORIES)
        return (
            f"(({alias}.extension IS NULL OR lower({alias}.extension) NOT IN ({exts})) "
            f"AND ({alias}.asset_category IS NULL OR {alias}.asset_category NOT IN ({cats})) "
            f"AND {alias}.is_static = false)"
        )

    # Backwards-compatible alias — the routing predicate is now a denylist.
    def _dynamic_predicate(self, alias: str) -> str:
        return self._target_predicate(alias)

    def count_dynamic(self, db: Session, scope_id: uuid.UUID) -> int:
        sql = f"""
            SELECT
                (SELECT count(*) FROM urls u
                    WHERE u.scope_id = :scope_id AND {self._dynamic_predicate('u')})
              + (SELECT count(*) FROM endpoints e
                    WHERE e.scope_id = :scope_id AND {self._dynamic_predicate('e')})
        """
        return int(db.execute(text(sql), {"scope_id": str(scope_id)}).scalar() or 0)

    def iter_dynamic(
        self,
        db: Session,
        scope_id: uuid.UUID,
        *,
        batch_size: int = 1000,
        after_url_id: uuid.UUID | None = None,
        after_endpoint_id: uuid.UUID | None = None,
    ) -> Iterator[DynamicAsset]:
        """Yield dynamic assets for the scope, urls first then endpoints.

        Uses id-keyset pagination per table so processing stays O(batch) in
        memory. ``after_url_id`` / ``after_endpoint_id`` resume after a prior
        checkpoint (pause/resume support).
        """
        yield from self._iter_urls(db, scope_id, batch_size, after_url_id)
        yield from self._iter_endpoints(db, scope_id, batch_size, after_endpoint_id)

    def _iter_urls(
        self, db: Session, scope_id: uuid.UUID, batch_size: int,
        after_id: uuid.UUID | None,
    ) -> Iterator[DynamicAsset]:
        cursor = after_id
        while True:
            params = {"scope_id": str(scope_id), "limit": batch_size}
            cursor_clause = ""
            if cursor is not None:
                cursor_clause = "AND u.id > :cursor"
                params["cursor"] = str(cursor)
            sql = f"""
                SELECT u.id AS id, u.normalized_url AS url, u.host AS host, u.host_id AS host_id
                FROM urls u
                WHERE u.scope_id = :scope_id AND {self._dynamic_predicate('u')}
                {cursor_clause}
                ORDER BY u.id
                LIMIT :limit
            """
            rows = db.execute(text(sql), params).mappings().all()
            if not rows:
                break
            for r in rows:
                cursor = r["id"]
                yield DynamicAsset(
                    asset_id=r["id"], asset_type="URL", url=r["url"],
                    host=r["host"], host_id=r["host_id"],
                )
            if len(rows) < batch_size:
                break

    def _iter_endpoints(
        self, db: Session, scope_id: uuid.UUID, batch_size: int,
        after_id: uuid.UUID | None,
    ) -> Iterator[DynamicAsset]:
        cursor = after_id
        while True:
            params = {"scope_id": str(scope_id), "limit": batch_size}
            cursor_clause = ""
            if cursor is not None:
                cursor_clause = "AND e.id > :cursor"
                params["cursor"] = str(cursor)
            sql = f"""
                SELECT e.id AS id, e.normalized_url AS url, e.host AS host, e.host_id AS host_id
                FROM endpoints e
                WHERE e.scope_id = :scope_id AND {self._dynamic_predicate('e')}
                {cursor_clause}
                ORDER BY e.id
                LIMIT :limit
            """
            rows = db.execute(text(sql), params).mappings().all()
            if not rows:
                break
            for r in rows:
                cursor = r["id"]
                yield DynamicAsset(
                    asset_id=r["id"], asset_type="ENDPOINT", url=r["url"],
                    host=r["host"], host_id=r["host_id"],
                )
            if len(rows) < batch_size:
                break
