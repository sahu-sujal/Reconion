"""Asset classification worker (Phase 6.3) — standalone, manually startable.

ONE responsibility: (re)classify every content asset (URLs, endpoints, JS files)
in a scope by *what it is* — API, JavaScript, Document, Archive, Configuration,
Credential, … — writing the classification columns back **in place**.

The same classification also runs automatically as a hook inside the JS-endpoint
worker after endpoints persist. This worker exposes it as a ``scan_type =
CLASSIFICATION`` scan so an analyst can re-run it on demand (e.g. after tweaking
the taxonomy, or on a scope whose content predates classification) without
re-running the whole discovery pipeline.

No network requests are made — it classifies data already in the database, so it
is safe to re-run at any time and is idempotent (re-running recomputes the same
columns). It does not chain any downstream scan.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import update

from backend.celery_app import celery_app
from backend.queues.redis_client import release_scope_lock
from backend.services.classification_service import (
    ClassificationMetrics,
    ClassificationService,
)
from backend.services.program_service import ProgramService
from backend.services.scope_service import ScopeService
from backend.services.storage_service import StorageService
from database.models.enums import ToolExecutionStatus
from database.models.scan_run import ScanRun
from repositories.tool_execution_repository import ToolExecutionRepository
from workers.base.base_worker import BaseWorker


class ClassificationWorker(BaseWorker):
    def __init__(self) -> None:
        super().__init__(name="classification_worker")
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
        metrics = ClassificationMetrics()

        try:
            scan_run_uuid = uuid.UUID(scan_run_id)
            scan_run, program, scope = self._load_scan_data(db, scan_run_uuid)
            self.mark_running(scan_run_id)

            self.storage_service.init_scope_directories_by_id(program.id, scope.id)
            proc_dir = self.storage_service.get_processed_path_by_id(
                program.id, scope.id, "classification",
            )

            # Honour a stop signal issued before we start the (single, atomic)
            # classification pass — once it begins it runs to completion.
            if self.check_control(scan_run_id) == "STOP":
                self.mark_cancelled(scan_run_id)
                return

            exec_rec = self._create_tool_execution(
                db, scan_run.id, "asset_classifier",
                "asset classification (in-process, no network)",
            )
            try:
                metrics = ClassificationService().classify_scope(db, scope.id)
                self._finalize_tool_execution(
                    db, exec_rec, ToolExecutionStatus.COMPLETED,
                    raw_records_found=metrics.total,
                    records_found=metrics.total,
                )
            except Exception as exc:
                self._finalize_tool_execution(
                    db, exec_rec, ToolExecutionStatus.FAILED, error_message=str(exc),
                )
                raise

            # ---- Persist summary artifact -------------------------- #
            summary = {
                "scan_run_id": str(scan_run.id),
                "urls_classified": metrics.urls_classified,
                "endpoints_classified": metrics.endpoints_classified,
                "js_classified": metrics.js_classified,
                "total": metrics.total,
                "by_category": metrics.by_category,
            }
            (proc_dir / "classification_summary.json").write_text(
                json.dumps(summary, indent=2), encoding="utf-8",
            )

            self._update_scan_metrics(db, scan_run.id, metrics)
            self.mark_completed(scan_run_id, records_found=metrics.total)

            self.logger.info(
                "Classification scan %s done — urls=%d endpoints=%d js=%d total=%d "
                "categories=%s",
                scan_run_id, metrics.urls_classified, metrics.endpoints_classified,
                metrics.js_classified, metrics.total, metrics.by_category,
            )

        except Exception as exc:
            self.logger.exception("Classification scan %s failed: %s", scan_run_id, exc)
            self.mark_failed(scan_run_id, str(exc))
        finally:
            if scan_run is not None:
                try:
                    release_scope_lock(scan_run.scope_id)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Helpers (mirror the other workers)
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

    def _update_scan_metrics(
        self, db, scan_run_id: uuid.UUID, metrics: ClassificationMetrics,
    ) -> None:
        db.execute(
            update(ScanRun)
            .where(ScanRun.id == scan_run_id)
            .values(records_found=metrics.total)
        )
        db.commit()


# ------------------------------------------------------------------
# Celery task
# ------------------------------------------------------------------

@celery_app.task(
    name="workers.classification.classification_worker.run_classification_scan",
    bind=True,
)
def run_classification_scan(self, scan_run_id: str) -> None:
    ClassificationWorker().run_scan(scan_run_id)
