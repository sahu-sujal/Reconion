"""GF classification worker — security-relevance tagging.

ONE responsibility: tag every stored URL and endpoint in a scope with the gf
categories it matches (sqli, xss, lfi, redirect, ssrf, idor, …), so analysts can
browse the inventory by *security relevance* instead of by discovery source.

Pipeline (scan_type = GF)::

    stream urls     (keyset batches, constant memory)
        └─ match each normalized_url against the compiled gf pattern set
           bulk-update gf_tags / gf_tag_count / gf_classified_at
    stream endpoints (keyset batches)
        └─ same
    persist merged artifact → update ScanRun metrics → Discord

No network requests are made — this classifies data already in the database, so
it is safe to re-run at any time and is idempotent (re-running produces the same
tags and simply refreshes ``gf_classified_at``).

Patterns are evaluated in-process rather than by shelling out to the ``gf``
binary; see ``tools/gf/gf_matcher`` for why (``gf`` recursively greps the working
directory for ``-r`` patterns and ignores ``$HOME`` when locating its pattern
set).
"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text, update

from backend.celery_app import celery_app
from backend.queues.redis_client import release_scope_lock
from backend.services.program_service import ProgramService
from backend.services.scope_service import ScopeService
from backend.services.storage_service import StorageService
from database.models.enums import ToolExecutionStatus
from database.models.scan_run import ScanRun
from repositories.tool_execution_repository import ToolExecutionRepository
from tools.gf.gf_matcher import available_categories, load_patterns, match
from workers.base.base_worker import BaseWorker

BATCH_SIZE = 10_000


@dataclass
class GfMetrics:
    urls_scanned: int = 0
    urls_matched: int = 0
    endpoints_scanned: int = 0
    endpoints_matched: int = 0
    category_counts: Counter = field(default_factory=Counter)

    @property
    def total_scanned(self) -> int:
        return self.urls_scanned + self.endpoints_scanned

    @property
    def total_matched(self) -> int:
        return self.urls_matched + self.endpoints_matched


class GfWorker(BaseWorker):
    def __init__(self) -> None:
        super().__init__(name="gf_worker")
        self.program_service = ProgramService()
        self.scope_service = ScopeService()
        self.storage_service = StorageService()
        self.tool_execution_repo = ToolExecutionRepository()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run_scan(self, scan_run_id: str) -> None:
        db = self.get_db()
        scan_run = None
        metrics = GfMetrics()

        try:
            scan_run_uuid = uuid.UUID(scan_run_id)
            scan_run, program, scope = self._load_scan_data(db, scan_run_uuid)
            self.mark_running(scan_run_id)

            self.storage_service.init_scope_directories_by_id(program.id, scope.id)
            gf_dir = self.storage_service.get_phase_path_by_id(program.id, scope.id, "gf")
            raw_dir = self.storage_service.get_raw_path_by_id(program.id, scope.id, "gf")
            proc_dir = self.storage_service.get_processed_path_by_id(program.id, scope.id, "gf")

            patterns = load_patterns()
            categories = available_categories()
            self.logger.info(
                "GF scan %s: %d patterns loaded (%d URL-taggable categories)",
                scan_run_id, len(patterns), len(categories),
            )

            exec_rec = self._create_tool_execution(
                db, scan_run.id, "gf",
                f"gf (in-process) — {len(categories)} categories: {', '.join(categories)}",
            )

            try:
                # ---- URLs -------------------------------------------- #
                signal = self.check_control(scan_run_id)
                if signal == "STOP":
                    self.mark_cancelled(scan_run_id)
                    return
                self._classify_table(
                    db, "urls", scope.id, metrics, raw_dir, is_url=True,
                )

                # ---- Endpoints --------------------------------------- #
                signal = self.check_control(scan_run_id)
                if signal == "STOP":
                    self.mark_cancelled(scan_run_id)
                    return
                self._classify_table(
                    db, "endpoints", scope.id, metrics, raw_dir, is_url=False,
                )

                self._finalize_tool_execution(
                    db, exec_rec, ToolExecutionStatus.COMPLETED,
                    raw_records_found=metrics.total_scanned,
                    records_found=metrics.total_matched,
                )
            except Exception as exc:
                self._finalize_tool_execution(
                    db, exec_rec, ToolExecutionStatus.FAILED, error_message=str(exc),
                )
                raise

            # ---- Persist summary artifact -------------------------- #
            summary = {
                "scan_run_id": str(scan_run.id),
                "categories": categories,
                "urls_scanned": metrics.urls_scanned,
                "urls_matched": metrics.urls_matched,
                "endpoints_scanned": metrics.endpoints_scanned,
                "endpoints_matched": metrics.endpoints_matched,
                "category_counts": dict(metrics.category_counts.most_common()),
            }
            (proc_dir / "gf_summary.json").write_text(
                json.dumps(summary, indent=2), encoding="utf-8",
            )

            self._update_scan_metrics(db, scan_run.id, metrics)
            self.mark_completed(scan_run_id, records_found=metrics.total_matched)

            self.logger.info(
                "GF scan %s done — scanned=%d matched=%d top=%s",
                scan_run_id, metrics.total_scanned, metrics.total_matched,
                metrics.category_counts.most_common(5),
            )

            try:
                from workers.notification.discord_worker import send_gf_scan_notification
                send_gf_scan_notification(
                    webhook_url=None,
                    program_name=program.name,
                    scope_target=scope.target,
                    metrics=metrics,
                )
            except Exception as exc:
                self.logger.warning("GF notification failed: %s", exc)

        except Exception as exc:
            self.logger.exception("GF scan %s failed: %s", scan_run_id, exc)
            self.mark_failed(scan_run_id, str(exc))
        finally:
            if scan_run is not None:
                try:
                    release_scope_lock(scan_run.scope_id)
                except Exception:
                    pass
            db.close()

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify_table(
        self,
        db,
        table: str,
        scope_id: uuid.UUID,
        metrics: GfMetrics,
        raw_dir,
        *,
        is_url: bool,
    ) -> None:
        """Stream one inventory table in keyset batches and tag each row.

        Keyset pagination on ``id`` keeps memory constant regardless of how many
        URLs a scope has, and avoids OFFSET's growing cost on large tables.
        """
        # urls store the canonical form in normalized_url; endpoints keep the
        # fully-qualified absolute_url alongside their normalized form.
        value_col = "normalized_url"
        after: uuid.UUID | None = None
        matched_samples: list[dict[str, Any]] = []

        while True:
            params: dict[str, Any] = {"scope_id": str(scope_id), "limit": BATCH_SIZE}
            cursor_clause = ""
            if after is not None:
                cursor_clause = "AND id > :after"
                params["after"] = str(after)

            rows = db.execute(
                text(f"""
                    SELECT id, {value_col} AS value
                    FROM {table}
                    WHERE scope_id = :scope_id {cursor_clause}
                    ORDER BY id
                    LIMIT :limit
                """),
                params,
            ).fetchall()

            if not rows:
                break
            after = rows[-1].id

            updates: list[dict[str, Any]] = []
            for row in rows:
                tags = match(row.value or "")
                updates.append({
                    "id": str(row.id),
                    "tags": json.dumps(tags),
                    "count": len(tags),
                })
                if tags:
                    metrics.category_counts.update(tags)
                    if len(matched_samples) < 1000:
                        matched_samples.append({"url": row.value, "tags": tags})

            self._bulk_update_tags(db, table, updates)

            scanned = len(rows)
            matched = sum(1 for u in updates if u["count"] > 0)
            if is_url:
                metrics.urls_scanned += scanned
                metrics.urls_matched += matched
            else:
                metrics.endpoints_scanned += scanned
                metrics.endpoints_matched += matched

            self.logger.info(
                "GF %s: %d scanned / %d matched so far",
                table,
                metrics.urls_scanned if is_url else metrics.endpoints_scanned,
                metrics.urls_matched if is_url else metrics.endpoints_matched,
            )

            if len(rows) < BATCH_SIZE:
                break

        if matched_samples:
            (raw_dir / f"{table}_gf_matches.json").write_text(
                json.dumps(matched_samples, indent=2), encoding="utf-8",
            )

    def _bulk_update_tags(self, db, table: str, rows: list[dict[str, Any]]) -> None:
        """Apply gf tags to many rows in one UPDATE ... FROM (VALUES ...)."""
        if not rows:
            return
        now = datetime.now(timezone.utc)
        chunk_size = 5000
        for start in range(0, len(rows), chunk_size):
            chunk = rows[start:start + chunk_size]
            placeholders = []
            flat: dict[str, Any] = {}
            for i, row in enumerate(chunk):
                if i == 0:
                    placeholders.append(
                        f"(CAST(:id_{i} AS uuid), CAST(:t_{i} AS jsonb), CAST(:c_{i} AS integer))"
                    )
                else:
                    placeholders.append(f"(:id_{i}, CAST(:t_{i} AS jsonb), :c_{i})")
                flat[f"id_{i}"] = row["id"]
                flat[f"t_{i}"] = row["tags"]
                flat[f"c_{i}"] = row["count"]
            flat["now"] = now
            db.execute(
                text(f"""
                    UPDATE {table} AS t SET
                        gf_tags = v.tags,
                        gf_tag_count = v.cnt,
                        gf_classified_at = :now,
                        updated_at = now()
                    FROM (VALUES {", ".join(placeholders)}) AS v(id, tags, cnt)
                    WHERE t.id = v.id
                """),
                flat,
            )
        db.commit()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_scan_data(self, db, scan_run_id: uuid.UUID):
        from backend.services.scan_run_service import ScanRunService
        svc = ScanRunService()
        scan_run = svc.get_scan_run(db=db, scan_run_id=scan_run_id)
        program = self.program_service.get_program(db=db, program_id=scan_run.program_id)
        scope = self.scope_service.get_scope(db=db, scope_id=scan_run.scope_id)
        return scan_run, program, scope

    def _create_tool_execution(self, db, scan_run_id: uuid.UUID, tool_name: str, command: str):
        return self.tool_execution_repo.create(
            db,
            scan_run_id=scan_run_id,
            tool_name=tool_name,
            command=command[:2000],
            status=ToolExecutionStatus.RUNNING.value,
            started_at=datetime.now(timezone.utc),
        )

    def _finalize_tool_execution(
        self, db, tool_execution, status: ToolExecutionStatus,
        error_message: str | None = None,
        raw_records_found: int = 0,
        records_found: int = 0,
    ) -> None:
        self.tool_execution_repo.update(
            db, tool_execution,
            status=status.value,
            error_message=error_message,
            raw_records_found=raw_records_found,
            records_found=records_found,
            finished_at=datetime.now(timezone.utc),
        )

    def _update_scan_metrics(self, db, scan_run_id: uuid.UUID, metrics: GfMetrics) -> None:
        db.execute(
            update(ScanRun)
            .where(ScanRun.id == scan_run_id)
            .values(records_found=metrics.total_matched)
        )
        db.commit()


# ------------------------------------------------------------------
# Celery task
# ------------------------------------------------------------------

@celery_app.task(name="workers.gf.gf_worker.run_gf_scan", bind=True)
def run_gf_scan(self, scan_run_id: str) -> None:
    GfWorker().run_scan(scan_run_id)
