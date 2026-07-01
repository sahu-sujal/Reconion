"""DNS resolution worker — Phase 4.

Pipeline per scan:

    1.  Load all discovered subdomains for this scope from DB
    2.  Run dnsx against all subdomains (single pass, JSON output)
    3.  Bulk-upsert Asset rows (type=HOST) for each resolved host
    4.  Bulk-upsert Host rows  (scope_id, host unique key)
    5.  Bulk-upsert DnsRecord rows (host_id, type, value unique key)
    6.  Update ScanRun metrics
    7.  Send Discord notification

Tool failures are isolated — a dnsx error marks the scan FAILED with a
message but does not crash the Celery worker process itself.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import update

from backend.celery_app import celery_app
from backend.queues.redis_client import release_scope_lock
from backend.services.program_service import ProgramService
from backend.services.scope_service import ScopeService
from backend.services.storage_service import StorageService
from database.models.enums import ToolExecutionStatus
from database.models.scan_run import ScanRun
from repositories.asset_repository import AssetRepository
from repositories.dns_record_repository import DnsRecordRepository
from repositories.host_repository import HostRepository
from repositories.subdomain_repository import SubdomainRepository
from repositories.tool_execution_repository import ToolExecutionRepository
from tools.dns.dnsx_runner import DnsxRecord, DnsxRunner
from workers.base.base_worker import BaseWorker

DB_BATCH_SIZE = 10_000


@dataclass
class DnsMetrics:
    dnsx_input: int = 0
    dnsx_resolved: int = 0
    new_hosts: int = 0
    existing_hosts: int = 0
    dns_records_inserted: int = 0


class DnsScanWorker(BaseWorker):
    def __init__(self) -> None:
        super().__init__(name="dns_worker")
        self.program_service = ProgramService()
        self.scope_service = ScopeService()
        self.storage_service = StorageService()
        self.subdomain_repo = SubdomainRepository()
        self.asset_repo = AssetRepository()
        self.host_repo = HostRepository()
        self.dns_record_repo = DnsRecordRepository()
        self.tool_execution_repo = ToolExecutionRepository()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run_scan(self, scan_run_id: str) -> None:
        db = self.get_db()
        scan_run = None
        metrics = DnsMetrics()

        try:
            scan_run_uuid = uuid.UUID(scan_run_id)
            scan_run, program, scope = self._load_scan_data(db, scan_run_uuid)

            # Resume path: a scan paused before chaining only needs to chain HTTP.
            resume = scan_run.resume_state or {}
            if resume.get("pending_chain") == "HTTP":
                self.mark_completed(scan_run_id, records_found=scan_run.records_found or 0)
                self.scan_run_service.update_scan_run(
                    db=db, scan_run_id=scan_run_id, clear_resume_state=True,
                )
                self._chain_http_scan(db, program.id, scope.id)
                return

            self.mark_running(scan_run_id)

            # Ensure UUID-based storage directories exist
            self.storage_service.init_scope_directories_by_id(program.id, scope.id)
            raw_dir = self.storage_service.get_raw_path_by_id(program.id, scope.id, "dns")
            proc_dir = self.storage_service.get_processed_path_by_id(program.id, scope.id, "dns")

            now = datetime.now(timezone.utc)

            # ---- Step 1: Load subdomains -------------------------------- #
            subdomains, subdomain_to_id = self._load_subdomains(db, scope.id)
            metrics.dnsx_input = len(subdomains)
            self.logger.info("DNS scan: %d subdomains to resolve", metrics.dnsx_input)

            if not subdomains:
                self._update_scan_metrics(db, scan_run.id, metrics)
                self.mark_completed(scan_run_id, records_found=0)
                return

            # ---- Step 2: Run dnsx -------------------------------------- #
            exec_rec = self._create_tool_execution(
                db, scan_run.id, "dnsx",
                f"dnsx -l <subdomains.txt> -a -aaaa -cname -mx -txt -ns -resp -json",
            )
            try:
                runner = DnsxRunner(timeout=900)
                dns_records_raw: list[DnsxRecord] = runner.resolve(subdomains)
                metrics.dnsx_resolved = len(dns_records_raw)

                # Persist raw dnsx JSON to disk
                raw_path = raw_dir / "dnsx.json"
                raw_path.write_text(
                    "\n".join(
                        json.dumps({
                            "host": r.host,
                            "a": r.a, "aaaa": r.aaaa, "cname": r.cname,
                            "mx": r.mx, "txt": r.txt, "ns": r.ns, "ttl": r.ttl,
                        })
                        for r in dns_records_raw
                    ),
                    encoding="utf-8",
                )

                self._finalize_tool_execution(
                    db, exec_rec, ToolExecutionStatus.COMPLETED,
                    raw_records_found=metrics.dnsx_input,
                    records_found=metrics.dnsx_resolved,
                )
            except RuntimeError as exc:
                self._finalize_tool_execution(
                    db, exec_rec, ToolExecutionStatus.FAILED, error_message=str(exc)
                )
                raise

            # ---- Step 3-5: Persist hosts + DNS records ------------------ #
            resolved_hosts = self._persist_resolved_hosts(
                db, scan_run.id, scope.id, program.id,
                dns_records_raw, now, metrics, subdomain_to_id,
            )

            # Write processed file — resolved hostnames
            proc_path = proc_dir / "resolved.txt"
            proc_path.write_text("\n".join(sorted(resolved_hosts)), encoding="utf-8")

            # ---- Step 6: Metrics --------------------------------------- #
            self._update_scan_metrics(db, scan_run.id, metrics)
            self.mark_completed(scan_run_id, records_found=metrics.dnsx_resolved)

            self.logger.info(
                "DNS scan %s done — resolved=%d new_hosts=%d dns_records=%d",
                scan_run_id, metrics.dnsx_resolved, metrics.new_hosts,
                metrics.dns_records_inserted,
            )

            # ---- Step 7: Discord --------------------------------------- #
            from workers.notification.discord_worker import send_dns_scan_notification
            send_dns_scan_notification(
                webhook_url=None,
                program_name=program.name,
                scope_target=scope.target,
                metrics=metrics,
            )

            # ---- Step 8: Chain HTTP scan ------------------------------- #
            if metrics.dnsx_resolved > 0:
                signal = self.check_control(scan_run_id)
                if signal == "STOP":
                    self.logger.info("Scan %s stopped before chaining HTTP", scan_run_id)
                    self.mark_cancelled(scan_run_id)
                    return
                if signal == "PAUSE":
                    self.logger.info("Scan %s paused before chaining HTTP", scan_run_id)
                    self.mark_paused(scan_run_id, resume_state={"pending_chain": "HTTP"})
                    return
                try:
                    self._chain_http_scan(db, program.id, scope.id)
                except Exception as chain_exc:
                    self.logger.warning(
                        "Failed to chain HTTP scan after DNS scan %s: %s",
                        scan_run_id, chain_exc,
                    )

        except Exception as exc:
            self.logger.exception("DNS scan %s failed: %s", scan_run_id, exc)
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

    def _load_subdomains(
        self, db, scope_id: uuid.UUID
    ) -> tuple[list[str], dict[str, uuid.UUID]]:
        """Stream all subdomains for scope; return (fqdn_list, fqdn→subdomain_id map)."""
        fqdns: list[str] = []
        subdomain_to_id: dict[str, uuid.UUID] = {}
        after: str | None = None
        while True:
            batch = self.subdomain_repo.list_by_scope(
                db, scope_id, limit=10_000, after_subdomain=after,
            )
            if not batch:
                break
            for s in batch:
                fqdns.append(s.subdomain)
                subdomain_to_id[s.subdomain] = s.id
            after = batch[-1].subdomain
        return fqdns, subdomain_to_id

    def _persist_resolved_hosts(
        self,
        db,
        scan_run_id: uuid.UUID,
        scope_id: uuid.UUID,
        program_id: uuid.UUID,
        dns_records: list[DnsxRecord],
        now: datetime,
        metrics: DnsMetrics,
        subdomain_to_id: dict[str, uuid.UUID] | None = None,
    ) -> list[str]:
        """Upsert Asset → Host → DnsRecord rows in batches.

        Returns the list of resolved host FQDNs.
        """
        resolved_hosts: list[str] = []

        for start in range(0, len(dns_records), DB_BATCH_SIZE):
            batch = dns_records[start:start + DB_BATCH_SIZE]

            # ---- Upsert Asset rows (type=HOST) ----
            asset_rows = [
                {
                    "id": uuid.uuid4(),
                    "program_id": program_id,
                    "scope_id": scope_id,
                    "asset_type": "HOST",
                    "asset_value": r.host,
                    "source": "dnsx",
                    "status": "active",
                    "first_seen": now,
                    "last_seen": now,
                    "created_at": now,
                    "updated_at": now,
                }
                for r in batch
            ]
            asset_value_to_id = self.asset_repo.bulk_upsert_subdomains(db, asset_rows)

            # ---- Upsert Host rows ----
            host_rows: list[dict[str, Any]] = []
            for rec in batch:
                asset_id = asset_value_to_id.get(rec.host)
                if not asset_id:
                    continue
                host_rows.append({
                    "id": uuid.uuid4(),
                    "asset_id": asset_id,
                    "program_id": program_id,
                    "scope_id": scope_id,
                    "host": rec.host,
                    "ip": rec.primary_ip,
                    "cdn": False,
                    "waf": False,
                    "first_seen": now,
                    "last_seen": now,
                    "created_at": now,
                    "updated_at": now,
                })

            new_host_rows, existing_host_rows = self.host_repo.bulk_upsert_staged(db, host_rows)
            metrics.new_hosts += len(new_host_rows)
            metrics.existing_hosts += len(existing_host_rows)

            # Build host_name → host_id mapping from DB results
            all_host_rows = new_host_rows + existing_host_rows
            host_name_to_id: dict[str, uuid.UUID] = {r["host"]: r["id"] for r in all_host_rows}

            # ---- Upsert DnsRecord rows ----
            dns_rows: list[dict[str, Any]] = []
            for rec in batch:
                host_id = host_name_to_id.get(rec.host)
                if not host_id:
                    continue
                resolved_hosts.append(rec.host)
                subdomain_id = (subdomain_to_id or {}).get(rec.host)
                for rtype, values in (
                    ("A", rec.a), ("AAAA", rec.aaaa), ("CNAME", rec.cname),
                    ("MX", rec.mx), ("TXT", rec.txt), ("NS", rec.ns),
                ):
                    for val in values:
                        if val:
                            dns_rows.append({
                                "id": uuid.uuid4(),
                                "program_id": program_id,
                                "scope_id": scope_id,
                                "host_id": host_id,
                                "subdomain_id": subdomain_id,
                                "record_type": rtype,
                                "record_value": val,
                                "ttl": rec.ttl,
                                "created_at": now,
                                "updated_at": now,
                            })

            inserted, _ = self.dns_record_repo.bulk_upsert(db, dns_rows)
            metrics.dns_records_inserted += inserted

        return resolved_hosts

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

    def _chain_http_scan(self, db, program_id: uuid.UUID, scope_id: uuid.UUID) -> None:
        """Create an HTTP ScanRun and enqueue run_http_scan for automatic chaining."""
        from backend.services.scan_run_service import ScanRunService
        from database.models.enums import ScanStatus, ScanType

        svc = ScanRunService()
        http_scan = svc.create_scan_run(
            db=db,
            program_id=program_id,
            scope_id=scope_id,
            scan_type=ScanType.HTTP.value,
            worker_name="http_worker",
            status=ScanStatus.PENDING.value,
        )
        celery_app.send_task(
            "workers.http.http_worker.run_http_scan",
            args=[str(http_scan.id)],
            countdown=2,
        )
        self.logger.info("Chained HTTP scan %s for scope %s", http_scan.id, scope_id)

    def _update_scan_metrics(self, db, scan_run_id: uuid.UUID, metrics: DnsMetrics) -> None:
        db.execute(
            update(ScanRun)
            .where(ScanRun.id == scan_run_id)
            .values(
                dnsx_count=metrics.dnsx_input,
                resolved_count=metrics.dnsx_resolved,
                new_hosts_count=metrics.new_hosts,
            )
        )
        db.commit()


# ------------------------------------------------------------------
# Celery task
# ------------------------------------------------------------------

@celery_app.task(name="workers.dns.dns_worker.run_dns_scan", bind=True)
def run_dns_scan(self, scan_run_id: str) -> None:
    DnsScanWorker().run_scan(scan_run_id)
