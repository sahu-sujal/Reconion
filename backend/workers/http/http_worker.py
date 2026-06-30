"""HTTP probing worker — Phase 4.

Pipeline per scan:

    1.  Load all resolved hosts for this scope from DB
    2.  Run httpx against all hosts (JSON output)
    3.  Bulk-update Host rows with HTTP fields
    4.  Bulk-upsert HttpResponse rows
    5.  Bulk-upsert Technology rows
    6.  Update ScanRun metrics
    7.  Send Discord notification
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import update

from backend.celery_app import celery_app
from backend.queues.redis_client import release_scope_lock
from backend.services.program_service import ProgramService
from backend.services.scope_service import ScopeService
from backend.services.storage_service import StorageService
from database.models.enums import ToolExecutionStatus
from database.models.scan_run import ScanRun
from repositories.host_repository import HostRepository
from repositories.http_response_repository import HttpResponseRepository
from repositories.technology_repository import TechnologyRepository
from repositories.tool_execution_repository import ToolExecutionRepository
from tools.http.httpx_runner import HttpxRecord, HttpxRunner
from workers.base.base_worker import BaseWorker

DB_BATCH_SIZE = 5_000


@dataclass
class HttpMetrics:
    httpx_input: int = 0
    httpx_live: int = 0
    new_live: int = 0
    http_responses_inserted: int = 0
    technologies_found: int = 0
    status_distribution: dict = field(default_factory=dict)


class HttpScanWorker(BaseWorker):
    def __init__(self) -> None:
        super().__init__(name="http_worker")
        self.program_service = ProgramService()
        self.scope_service = ScopeService()
        self.storage_service = StorageService()
        self.host_repo = HostRepository()
        self.http_response_repo = HttpResponseRepository()
        self.technology_repo = TechnologyRepository()
        self.tool_execution_repo = ToolExecutionRepository()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run_scan(self, scan_run_id: str) -> None:
        db = self.get_db()
        scan_run = None
        metrics = HttpMetrics()

        try:
            scan_run_uuid = uuid.UUID(scan_run_id)
            scan_run, program, scope = self._load_scan_data(db, scan_run_uuid)
            self.mark_running(scan_run_id)

            self.storage_service.init_scope_directories_by_id(program.id, scope.id)
            raw_dir = self.storage_service.get_raw_path_by_id(program.id, scope.id, "http")
            proc_dir = self.storage_service.get_processed_path_by_id(program.id, scope.id, "http")

            now = datetime.now(timezone.utc)

            # ---- Step 1: Load resolved hosts from DB ------------------- #
            hosts = self._load_hosts(db, scope.id)
            metrics.httpx_input = len(hosts)
            self.logger.info("HTTP scan: %d hosts to probe", metrics.httpx_input)

            if not hosts:
                self._update_scan_metrics(db, scan_run.id, metrics)
                self.mark_completed(scan_run_id, records_found=0)
                return

            # ---- Step 2: Run httpx ------------------------------------- #
            exec_rec = self._create_tool_execution(
                db, scan_run.id, "httpx",
                "httpx -l <hosts.txt> -json -silent -title -status-code -content-length "
                "-ip -server -tech-detect -cdn -response-time",
            )
            try:
                runner = HttpxRunner(timeout=900, threads=200)
                http_records: list[HttpxRecord] = runner.probe(hosts)
                metrics.httpx_live = len(http_records)

                # Persist raw httpx JSON to disk
                raw_path = raw_dir / "httpx.json"
                raw_path.write_text(
                    "\n".join(
                        json.dumps({
                            "url": r.url, "host": r.host, "scheme": r.scheme,
                            "port": r.port, "ip": r.ip, "status_code": r.status_code,
                            "title": r.title, "content_length": r.content_length,
                            "server": r.server, "technologies": r.technologies,
                            "response_time": r.response_time,
                            "cdn": r.cdn, "waf": r.waf,
                        })
                        for r in http_records
                    ),
                    encoding="utf-8",
                )

                self._finalize_tool_execution(
                    db, exec_rec, ToolExecutionStatus.COMPLETED,
                    raw_records_found=metrics.httpx_input,
                    records_found=metrics.httpx_live,
                )
            except RuntimeError as exc:
                self._finalize_tool_execution(
                    db, exec_rec, ToolExecutionStatus.FAILED, error_message=str(exc)
                )
                raise

            # ---- Steps 3-5: Persist HTTP results ----------------------- #
            live_urls = self._persist_http_results(
                db, scope.id, program.id, http_records, now, metrics,
            )

            # Write processed file — live URLs
            proc_path = proc_dir / "live.txt"
            proc_path.write_text("\n".join(sorted(live_urls)), encoding="utf-8")

            # ---- Step 6: Metrics --------------------------------------- #
            self._update_scan_metrics(db, scan_run.id, metrics)
            self.mark_completed(scan_run_id, records_found=metrics.httpx_live)

            self.logger.info(
                "HTTP scan %s done — live=%d responses=%d technologies=%d",
                scan_run_id, metrics.httpx_live,
                metrics.http_responses_inserted, metrics.technologies_found,
            )

            # ---- Step 7: Discord --------------------------------------- #
            from workers.notification.discord_worker import send_http_scan_notification
            send_http_scan_notification(
                webhook_url=None,
                program_name=program.name,
                scope_target=scope.target,
                metrics=metrics,
            )

            # ---- Step 8: Chain content discovery ----------------------- #
            if metrics.httpx_live > 0:
                try:
                    self._chain_content_discovery(db, program.id, scope.id)
                except Exception as chain_exc:
                    self.logger.warning(
                        "Failed to chain content discovery after HTTP scan %s: %s",
                        scan_run_id, chain_exc,
                    )

        except Exception as exc:
            self.logger.exception("HTTP scan %s failed: %s", scan_run_id, exc)
            self.mark_failed(scan_run_id, str(exc))
        finally:
            if scan_run is not None:
                try:
                    release_scope_lock(scan_run.scope_id)
                except Exception:
                    pass
            db.close()

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _load_hosts(self, db, scope_id: uuid.UUID) -> list[str]:
        """Stream all resolved host strings in batches."""
        results: list[str] = []
        after: str | None = None
        while True:
            batch = self.host_repo.list_by_scope(
                db, scope_id, limit=10_000, after_host=after,
            )
            if not batch:
                break
            results.extend(h.host for h in batch)
            after = batch[-1].host
        return results

    def _persist_http_results(
        self,
        db,
        scope_id: uuid.UUID,
        program_id: uuid.UUID,
        http_records: list[HttpxRecord],
        now: datetime,
        metrics: HttpMetrics,
    ) -> list[str]:
        """Update Host rows and upsert HttpResponse + Technology rows."""
        live_urls: list[str] = []

        # Build host→record map (keep first record per host for update)
        host_map: dict[str, HttpxRecord] = {}
        for rec in http_records:
            if rec.host not in host_map:
                host_map[rec.host] = rec

        # Fetch existing host IDs for this scope in one query
        from sqlalchemy import select
        from database.models.host import Host
        host_rows_db = db.execute(
            select(Host.host, Host.id, Host.status_code).where(Host.scope_id == scope_id)
        ).fetchall()
        host_name_to_id: dict[str, uuid.UUID] = {r.host: r.id for r in host_rows_db}
        # Hosts that were already live (had a status code) before this scan.
        # Used to count hosts that become live for the first time this run.
        prev_live: set[str] = {r.host for r in host_rows_db if r.status_code is not None}
        counted_new_live: set[str] = set()

        for start in range(0, len(http_records), DB_BATCH_SIZE):
            batch = http_records[start:start + DB_BATCH_SIZE]

            # ---- Update Host rows with HTTP metadata (single statement) ----
            host_updates: list[dict[str, Any]] = []
            for rec in batch:
                host_id = host_name_to_id.get(rec.host)
                if not host_id:
                    continue
                if rec.host not in prev_live and rec.host not in counted_new_live:
                    metrics.new_live += 1
                    counted_new_live.add(rec.host)
                host_updates.append({
                    "id": host_id,
                    "scheme": rec.scheme,
                    "port": rec.port,
                    "ip": rec.ip,
                    "status_code": rec.status_code,
                    "title": rec.title[:512] if rec.title else None,
                    "content_length": rec.content_length,
                    "response_time": rec.response_time,
                    "cdn": rec.cdn,
                    "waf": rec.waf,
                    "last_seen": now,
                })
            self.host_repo.bulk_update_http_fields(db, host_updates)

            # ---- Upsert HttpResponse rows ----
            http_rows: list[dict[str, Any]] = []
            for rec in batch:
                host_id = host_name_to_id.get(rec.host)
                if not host_id:
                    continue
                live_urls.append(rec.url)
                http_rows.append({
                    "id": uuid.uuid4(),
                    "program_id": program_id,
                    "scope_id": scope_id,
                    "host_id": host_id,
                    "url": rec.url,
                    "status_code": rec.status_code,
                    "title": rec.title[:512] if rec.title else None,
                    "content_length": rec.content_length,
                    "server": rec.server,
                    "technologies": json.dumps(rec.technologies) if rec.technologies else None,
                    "response_time": rec.response_time,
                    "created_at": now,
                    "updated_at": now,
                })
                # Count status distribution
                sc = rec.status_code
                if sc is not None:
                    metrics.status_distribution[sc] = metrics.status_distribution.get(sc, 0) + 1

            inserted, _ = self.http_response_repo.bulk_upsert(db, http_rows)
            metrics.http_responses_inserted += inserted

            # ---- Upsert Technology rows ----
            tech_rows: list[dict[str, Any]] = []
            for rec in batch:
                host_id = host_name_to_id.get(rec.host)
                if not host_id or not rec.technologies:
                    continue
                for tech_str in rec.technologies:
                    # httpx returns "TechName:version" or just "TechName"
                    if ":" in tech_str:
                        tech_name, version = tech_str.split(":", 1)
                    else:
                        tech_name, version = tech_str, None
                    tech_name = tech_name.strip()[:128]
                    if not tech_name:
                        continue
                    tech_rows.append({
                        "program_id": program_id,
                        "scope_id": scope_id,
                        "host_id": host_id,
                        "technology": tech_name,
                        "version": version[:64] if version else None,
                        "first_seen": now,
                        "last_seen": now,
                    })

            if tech_rows:
                metrics.technologies_found += self._upsert_technologies(db, tech_rows, now)

        return live_urls

    def _upsert_technologies(self, db, rows: list[dict[str, Any]], now: datetime) -> int:
        """Upsert technologies; returns count of inserted rows."""
        from sqlalchemy import text
        if not rows:
            return 0
        result = db.execute(
            text("""
                INSERT INTO technologies (
                    id, program_id, scope_id, host_id,
                    technology, version, first_seen, last_seen,
                    created_at, updated_at
                )
                VALUES (
                    gen_random_uuid(), :program_id, :scope_id, :host_id,
                    :technology, :version, :first_seen, :last_seen,
                    now(), now()
                )
                ON CONFLICT DO NOTHING
            """),
            rows,
        )
        count = result.rowcount
        db.commit()
        return count

    def _load_scan_data(self, db, scan_run_id: uuid.UUID):
        from backend.services.scan_run_service import ScanRunService
        svc = ScanRunService()
        scan_run = svc.get_scan_run(db=db, scan_run_id=scan_run_id)
        program = self.program_service.get_program(db=db, program_id=scan_run.program_id)
        scope = self.scope_service.get_scope(db=db, scope_id=scan_run.scope_id)
        return scan_run, program, scope

    def _chain_content_discovery(self, db, program_id: uuid.UUID, scope_id: uuid.UUID) -> None:
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

    def _update_scan_metrics(self, db, scan_run_id: uuid.UUID, metrics: HttpMetrics) -> None:
        db.execute(
            update(ScanRun)
            .where(ScanRun.id == scan_run_id)
            .values(
                httpx_count=metrics.httpx_input,
                live_count=metrics.httpx_live,
                new_live_count=metrics.new_live,
            )
        )
        db.commit()


# ------------------------------------------------------------------
# Celery task
# ------------------------------------------------------------------

@celery_app.task(name="workers.http.http_worker.run_http_scan", bind=True)
def run_http_scan(self, scan_run_id: str) -> None:
    HttpScanWorker().run_scan(scan_run_id)
