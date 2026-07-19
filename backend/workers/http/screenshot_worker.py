"""Screenshot worker — captures page screenshots for live hosts with gowitness.

Post-HTTP phase. It captures visual evidence before content discovery begins.
Pipeline per scan:

    1.  Load all live hosts (status_code set) for this scope from DB
    2.  Build one URL per host (scheme + host + port)
    3.  Run gowitness against the URLs, writing images to
        storage/programs/<pid>/scopes/<sid>/screenshots/
    4.  Bulk-upsert Screenshot rows (relative file_path per capture)
    5.  Update hosts.screenshot_count / hosts.screenshot_path
    6.  Update ScanRun metrics + record ToolExecution
    7.  Send Discord notification
    8.  Chain content discovery
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select, text, update

from backend.celery_app import celery_app
from backend.queues.redis_client import release_scope_lock
from backend.services.program_service import ProgramService
from backend.services.scope_service import ScopeService
from backend.services.storage_service import STORAGE_ROOT, StorageService
from database.models.enums import ToolExecutionStatus
from database.models.host import Host
from database.models.scan_run import ScanRun
from repositories.screenshot_repository import ScreenshotRepository
from repositories.tool_execution_repository import ToolExecutionRepository
from tools.http.gowitness_runner import GowitnessRecord, GowitnessRunner
from workers.base.base_worker import BaseWorker


@dataclass
class ScreenshotMetrics:
    hosts_input: int = 0
    captured: int = 0
    failed: int = 0


def _host_url(host: str, scheme: str | None, port: int | None) -> str:
    scheme = scheme or ("https" if port == 443 else "http")
    default_port = 443 if scheme == "https" else 80
    port_part = f":{port}" if port and port != default_port else ""
    # URL authorities require literal IPv6 addresses to be bracketed.
    authority = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"{scheme}://{authority}{port_part}"


def _hostname_of(url: str) -> str:
    """Extract the bare hostname from a URL (drop scheme, port, path)."""
    return (urlsplit(url).hostname or "").lower()


class ScreenshotWorker(BaseWorker):
    def __init__(self) -> None:
        super().__init__(name="screenshot_worker")
        self.program_service = ProgramService()
        self.scope_service = ScopeService()
        self.storage_service = StorageService()
        self.screenshot_repo = ScreenshotRepository()
        self.tool_execution_repo = ToolExecutionRepository()

    def run_scan(self, scan_run_id: str) -> None:
        db = self.get_db()
        scan_run = None
        metrics = ScreenshotMetrics()

        try:
            scan_run_uuid = uuid.UUID(scan_run_id)
            scan_run, program, scope = self._load_scan_data(db, scan_run_uuid)

            # Resume path: paused before chaining → just chain content discovery.
            resume = scan_run.resume_state or {}
            if resume.get("pending_chain") == "CONTENT_DISCOVERY":
                self.mark_completed(scan_run_id, records_found=scan_run.records_found or 0)
                self.scan_run_service.update_scan_run(
                    db=db, scan_run_id=scan_run_id, clear_resume_state=True,
                )
                self._chain_content_discovery_scan(db, program.id, scope.id)
                return

            self.mark_running(scan_run_id)

            self.storage_service.init_scope_directories_by_id(program.id, scope.id)
            screenshot_dir = self.storage_service.get_phase_path_by_id(
                program.id, scope.id, "screenshots",
            )
            now = datetime.now(timezone.utc)

            # ---- Step 1-2: Load live hosts & build URLs ----------------- #
            host_rows = db.execute(
                select(Host.id, Host.host, Host.scheme, Host.port)
                .where(Host.scope_id == scope.id, Host.status_code.isnot(None))
                .order_by(Host.host)
            ).fetchall()
            metrics.hosts_input = len(host_rows)
            self.logger.info("Screenshot scan: %d live hosts", metrics.hosts_input)

            if not host_rows:
                self._update_scan_metrics(db, scan_run.id, metrics)
                self.mark_completed(scan_run_id, records_found=0)
                # No hosts to capture, but content discovery still runs off
                # hostnames — screenshots must never be a pipeline dead end.
                self._chain_next_phase(db, scan_run_id, program.id, scope.id)
                return

            # gowitness expands each input URL into scheme/port variants and
            # reports them as "scheme://host:port", so we map its results back to
            # a host by bare hostname rather than exact URL string.
            host_by_name: dict[str, uuid.UUID] = {}
            urls: list[str] = []
            for r in host_rows:
                host_by_name[r.host.lower()] = r.id
                urls.append(_host_url(r.host, r.scheme, r.port))

            # ---- Step 3: Run gowitness --------------------------------- #
            exec_rec = self._create_tool_execution(
                db, scan_run.id, "gowitness",
                f"gowitness scan file -f <urls.txt> -s {screenshot_dir} "
                "--screenshot-format jpeg --write-jsonl",
            )
            try:
                runner = GowitnessRunner(timeout=1800, threads=15)
                records: list[GowitnessRecord] = runner.capture(urls, screenshot_dir)
                self._finalize_tool_execution(
                    db, exec_rec, ToolExecutionStatus.COMPLETED,
                    raw_records_found=len(urls),
                    records_found=sum(1 for r in records if not r.failed),
                )
            except RuntimeError as exc:
                self._finalize_tool_execution(
                    db, exec_rec, ToolExecutionStatus.FAILED, error_message=str(exc)
                )
                raise

            # ---- Step 4-5: Persist screenshots ------------------------- #
            self._persist_screenshots(
                db, scope.id, program.id, records, host_by_name, now, metrics,
            )

            # ---- Step 6: Metrics --------------------------------------- #
            self._update_scan_metrics(db, scan_run.id, metrics)
            self.mark_completed(scan_run_id, records_found=metrics.captured)

            self.logger.info(
                "Screenshot scan %s done — captured=%d failed=%d",
                scan_run_id, metrics.captured, metrics.failed,
            )

            # ---- Step 7: Discord --------------------------------------- #
            try:
                from workers.notification.discord_worker import (
                    send_screenshot_scan_notification,
                )
                send_screenshot_scan_notification(
                    webhook_url=None,
                    program_name=program.name,
                    scope_target=scope.target,
                    metrics=metrics,
                )
            except Exception as exc:
                self.logger.warning("Screenshot notification failed: %s", exc)

            # ---- Step 8: Chain content discovery ----------------------- #
            self._chain_next_phase(db, scan_run_id, program.id, scope.id)

        except Exception as exc:
            self.logger.exception("Screenshot scan %s failed: %s", scan_run_id, exc)
            self.mark_failed(scan_run_id, str(exc))
        finally:
            if scan_run is not None:
                try:
                    release_scope_lock(scan_run.scope_id)
                except Exception:
                    pass
            db.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _persist_screenshots(
        self,
        db,
        scope_id: uuid.UUID,
        program_id: uuid.UUID,
        records: list[GowitnessRecord],
        host_by_name: dict[str, uuid.UUID],
        now: datetime,
        metrics: ScreenshotMetrics,
    ) -> None:
        rows: list[dict[str, Any]] = []
        # host_id -> chosen relative screenshot path (for hosts.screenshot_path);
        # prefer an https capture so the host thumbnail is the canonical page.
        host_primary_path: dict[uuid.UUID, str] = {}

        for rec in records:
            host_id = host_by_name.get(_hostname_of(rec.url))
            if not host_id:
                continue

            file_path: str | None = None
            if rec.file_name and not rec.failed:
                abs_path = (
                    self.storage_service.get_phase_path_by_id(
                        program_id, scope_id, "screenshots",
                    )
                    / rec.file_name
                )
                try:
                    file_path = str(abs_path.relative_to(STORAGE_ROOT))
                except ValueError:
                    file_path = str(abs_path)
                metrics.captured += 1
                # Prefer an https capture as the host's primary thumbnail;
                # otherwise take the first successful one.
                if host_id not in host_primary_path or rec.url.startswith("https://"):
                    host_primary_path[host_id] = file_path
            else:
                metrics.failed += 1

            rows.append({
                "id": uuid.uuid4(),
                "program_id": program_id,
                "scope_id": scope_id,
                "host_id": host_id,
                "url": rec.url,
                "final_url": rec.final_url,
                "title": rec.title[:512] if rec.title else None,
                "status_code": rec.status_code,
                "file_name": rec.file_name,
                "file_path": file_path,
                "failed": rec.failed,
                "failed_reason": rec.failed_reason,
                "captured_at": now,
                "created_at": now,
                "updated_at": now,
            })

        if rows:
            self.screenshot_repo.bulk_upsert(db, rows)

        self._update_host_screenshots(db, host_primary_path)

    def _update_host_screenshots(
        self, db, host_latest_path: dict[uuid.UUID, str],
    ) -> None:
        """Set hosts.screenshot_path and refresh screenshot_count from the table."""
        if not host_latest_path:
            return
        rows = list(host_latest_path.items())
        chunk_size = 4000
        for start in range(0, len(rows), chunk_size):
            chunk = rows[start:start + chunk_size]
            placeholders = []
            flat: dict[str, Any] = {}
            for i, (hid, path) in enumerate(chunk):
                if i == 0:
                    placeholders.append(
                        f"(CAST(:id_{i} AS uuid), CAST(:p_{i} AS varchar))"
                    )
                else:
                    placeholders.append(f"(:id_{i}, :p_{i})")
                flat[f"id_{i}"] = str(hid)
                flat[f"p_{i}"] = path
            db.execute(
                text(f"""
                    UPDATE hosts AS h SET
                        screenshot_path = v.p,
                        screenshot_count = (
                            SELECT COUNT(*) FROM screenshots s
                            WHERE s.host_id = h.id AND s.failed = false
                        ),
                        updated_at = now()
                    FROM (VALUES {", ".join(placeholders)}) AS v(id, p)
                    WHERE h.id = v.id
                """),
                flat,
            )
        db.commit()

    def _load_scan_data(self, db, scan_run_id: uuid.UUID):
        from backend.services.scan_run_service import ScanRunService
        svc = ScanRunService()
        scan_run = svc.get_scan_run(db=db, scan_run_id=scan_run_id)
        program = self.program_service.get_program(db=db, program_id=scan_run.program_id)
        scope = self.scope_service.get_scope(db=db, scope_id=scan_run.scope_id)
        return scan_run, program, scope

    def _chain_next_phase(
        self, db, scan_run_id: str, program_id: uuid.UUID, scope_id: uuid.UUID,
    ) -> None:
        """Honour pause/stop control, then hand off to content discovery."""
        signal = self.check_control(scan_run_id)
        if signal == "STOP":
            self.logger.info("Scan %s stopped before chaining content discovery", scan_run_id)
            self.mark_cancelled(scan_run_id)
            return
        if signal == "PAUSE":
            self.logger.info("Scan %s paused before chaining content discovery", scan_run_id)
            self.mark_paused(scan_run_id, resume_state={"pending_chain": "CONTENT_DISCOVERY"})
            return
        try:
            self._chain_content_discovery_scan(db, program_id, scope_id)
        except Exception as chain_exc:
            self.logger.warning(
                "Failed to chain content discovery after screenshot scan %s: %s",
                scan_run_id, chain_exc,
            )

    def _chain_content_discovery_scan(
        self, db, program_id: uuid.UUID, scope_id: uuid.UUID,
    ) -> None:
        """Create a CONTENT_DISCOVERY ScanRun and enqueue run_url_scan."""
        from backend.services.scan_run_service import ScanRunService
        from database.models.enums import ScanStatus, ScanType

        svc = ScanRunService()
        url_scan = svc.create_scan_run(
            db=db,
            program_id=program_id,
            scope_id=scope_id,
            scan_type=ScanType.CONTENT_DISCOVERY.value,
            worker_name="url_worker",
            status=ScanStatus.PENDING.value,
        )
        celery_app.send_task(
            "workers.url.url_worker.run_url_scan",
            args=[str(url_scan.id)],
            countdown=2,
        )
        self.logger.info("Chained content discovery scan %s for scope %s", url_scan.id, scope_id)

    def _create_tool_execution(self, db, scan_run_id: uuid.UUID, tool_name: str, command: str):
        return self.tool_execution_repo.create(
            db,
            scan_run_id=scan_run_id,
            tool_name=tool_name,
            command=command,
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

    def _update_scan_metrics(self, db, scan_run_id: uuid.UUID, metrics: ScreenshotMetrics) -> None:
        db.execute(
            update(ScanRun)
            .where(ScanRun.id == scan_run_id)
            .values(records_found=metrics.captured)
        )
        db.commit()


# ------------------------------------------------------------------
# Celery task
# ------------------------------------------------------------------

@celery_app.task(name="workers.http.screenshot_worker.run_screenshot_scan", bind=True)
def run_screenshot_scan(self, scan_run_id: str) -> None:
    ScreenshotWorker().run_scan(scan_run_id)
