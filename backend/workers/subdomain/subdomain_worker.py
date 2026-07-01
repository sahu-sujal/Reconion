"""Subdomain discovery worker — Phase 3 (extended).

Pipeline per scan:

    1.  Subfinder    → raw/subfinder.txt
    2.  Assetfinder  → raw/assetfinder.txt
    3.  Knockpy      → raw/knockpy.txt
    4.  DNSGen       → raw/dnsgen.txt
    5.  Chaos        → raw/chaos.txt
    6.  CRT.SH       → raw/crtsh.txt
    7.  Findomain    → raw/findomain.txt
    8.  Disk-based sort-u merge of all in-scope raw files
                     → processed/subdomains.txt
    9.  Bulk upsert subdomains via ON CONFLICT (scope_id, subdomain)
    10. Bulk insert subdomain_sources rows (new assets only)
    11. Write diff/YYYY-MM-DDTHH-MM-SS-new.txt  (only new subdomains)
    12. Update scan_run metric columns
    13. Single Discord embed with full summary + new_assets.txt attachment

Tool failures are isolated — one failing tool does not abort the scan.
Disk-based merging via sort -u avoids loading 100 k+ entries into memory.
"""

from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text, update

from backend.celery_app import celery_app
from backend.queues.redis_client import release_scope_lock
from backend.services.program_service import ProgramService
from backend.services.scope_service import ScopeService
from backend.services.storage_service import StorageService
from database.models.enums import ToolExecutionStatus
from database.models.scan_run import ScanRun
from repositories.asset_repository import AssetRepository
from repositories.notification_repository import NotificationRepository
from repositories.subdomain_repository import SubdomainRepository
from repositories.subdomain_source_repository import SubdomainSourceRepository
from repositories.tool_execution_repository import ToolExecutionRepository
from tools.common.scope_filter import filter_in_scope
from tools.subdomain.assetfinder_runner import AssetfinderRunner
from tools.subdomain.chaos_runner import ChaosRunner
from tools.subdomain.crtsh_runner import CrtshRunner
from tools.subdomain.dnsgen_runner import DnsgenRunner
from tools.subdomain.findomain_runner import FindomainRunner
from tools.subdomain.knockpy_runner import KnockpyRunner
from tools.subdomain.subfinder_runner import SubfinderRunner
from workers.base.base_worker import BaseWorker
from workers.notification.discord_worker import send_scan_complete_notification

DB_UPSERT_BATCH_SIZE = 50_000
NOTIFICATION_SAMPLE_LIMIT = 1_000


# ------------------------------------------------------------------ #
# Metrics container                                                     #
# ------------------------------------------------------------------ #

@dataclass
class ScanMetrics:
    """Per-tool and aggregate counters accumulated during one scan run."""
    # raw = all lines returned by tool; count = in-scope after filter
    subfinder_raw: int = 0
    subfinder_count: int = 0
    assetfinder_raw: int = 0
    assetfinder_count: int = 0
    knockpy_raw: int = 0
    knockpy_count: int = 0
    dnsgen_raw: int = 0
    dnsgen_count: int = 0
    chaos_raw: int = 0
    chaos_count: int = 0
    crtsh_raw: int = 0
    crtsh_count: int = 0
    findomain_raw: int = 0
    findomain_count: int = 0
    # aggregate
    merged_count: int = 0    # sum of all in-scope counts (pre-dedup)
    unique_count: int = 0    # after disk-based deduplication
    new_count: int = 0       # newly inserted in DB
    existing_count: int = 0  # updated existing rows in DB


# ------------------------------------------------------------------ #
# Worker                                                                #
# ------------------------------------------------------------------ #

class SubdomainScanWorker(BaseWorker):
    def __init__(self) -> None:
        super().__init__(name="subdomain_worker")
        self.program_service = ProgramService()
        self.scope_service = ScopeService()
        self.storage_service = StorageService()
        self.asset_repo = AssetRepository()
        self.notification_repo = NotificationRepository()
        self.subdomain_repo = SubdomainRepository()
        self.subdomain_source_repo = SubdomainSourceRepository()
        self.tool_execution_repo = ToolExecutionRepository()

    # ------------------------------------------------------------------ #
    # Public entry point                                                    #
    # ------------------------------------------------------------------ #

    def run_scan(self, scan_run_id: str) -> None:
        db = self.get_db()
        scan_run = None
        metrics = ScanMetrics()

        try:
            scan_run_uuid = uuid.UUID(scan_run_id)
            scan_run, program, scope = self._load_scan_data(db, scan_run_uuid)

            # Resume path: a scan paused *before chaining* only needs to chain
            # the next phase — its own tools already ran and were persisted.
            resume = scan_run.resume_state or {}
            if resume.get("pending_chain") == "DNS":
                self.mark_completed(scan_run_id, records_found=scan_run.records_found or 0)
                self.scan_run_service.update_scan_run(
                    db=db, scan_run_id=scan_run_id, clear_resume_state=True,
                )
                self._chain_dns_scan(db, program.id, scope.id)
                return

            self.mark_running(scan_run_id)
            self.storage_service.init_scope_directories_by_id(program.id, scope.id)

            raw_dir = self.storage_service.get_raw_path_by_id(program.id, scope.id, "subdomains")
            proc_dir = self.storage_service.get_processed_path_by_id(program.id, scope.id, "subdomains")
            now = datetime.now(timezone.utc)

            # ---- Steps 1-7: Run all enumeration tools ----------------- #
            # source_map[subdomain] = sorted comma-sep tool names
            source_map: dict[str, set[str]] = {}

            self._run_tool(db, scan_run, scope, program, metrics, raw_dir, source_map,
                           "subfinder", SubfinderRunner(timeout=300),
                           "subfinder_raw", "subfinder_count")

            self._run_tool(db, scan_run, scope, program, metrics, raw_dir, source_map,
                           "assetfinder", AssetfinderRunner(timeout=300),
                           "assetfinder_raw", "assetfinder_count")

            self._run_tool(db, scan_run, scope, program, metrics, raw_dir, source_map,
                           "knockpy", KnockpyRunner(timeout=600),
                           "knockpy_raw", "knockpy_count")

            self._run_tool(db, scan_run, scope, program, metrics, raw_dir, source_map,
                           "dnsgen", DnsgenRunner(timeout=300),
                           "dnsgen_raw", "dnsgen_count")

            self._run_tool(db, scan_run, scope, program, metrics, raw_dir, source_map,
                           "chaos", ChaosRunner(timeout=300),
                           "chaos_raw", "chaos_count")

            self._run_tool(db, scan_run, scope, program, metrics, raw_dir, source_map,
                           "crtsh", CrtshRunner(timeout=120),
                           "crtsh_raw", "crtsh_count")

            self._run_tool(db, scan_run, scope, program, metrics, raw_dir, source_map,
                           "findomain", FindomainRunner(timeout=300),
                           "findomain_raw", "findomain_count")

            # ---- Step 8: Disk-based merge + dedup -------------------- #
            metrics.merged_count = (
                metrics.subfinder_count + metrics.assetfinder_count +
                metrics.knockpy_count + metrics.dnsgen_count +
                metrics.chaos_count + metrics.crtsh_count +
                metrics.findomain_count
            )

            processed_path = proc_dir / "subdomains.txt"
            unique_subdomains = self._merge_raw_files(raw_dir, processed_path, scope.target)
            metrics.unique_count = len(unique_subdomains)

            self.logger.info(
                "Merge complete — merged: %d, unique: %d",
                metrics.merged_count, metrics.unique_count,
            )

            # Rebuild source_map so only subdomains that survived dedup are keyed
            # (tools may have returned out-of-scope entries that were already filtered
            # before populating source_map, so this is consistent)
            final_source_map: dict[str, str] = {
                sub: ",".join(sorted(source_map.get(sub, set())))
                for sub in unique_subdomains
            }

            # ---- Step 9-11: Bulk upsert + diff ---------------------- #
            new_subdomains_sample: list[str] = []
            if unique_subdomains:
                new_subdomains_sample = self._bulk_upsert_subdomains(
                    db, scan_run.id, scope.id, program.id,
                    unique_subdomains, final_source_map, now, metrics,
                )

            # ---- Step 12: Update scan_run metric columns ------------- #
            self._update_scan_metrics(db, scan_run.id, metrics)

            self.mark_completed(scan_run_id, records_found=metrics.unique_count)
            self.logger.info(
                "Scan %s done — unique=%d new=%d existing=%d",
                scan_run_id, metrics.unique_count, metrics.new_count,
                metrics.existing_count,
            )

            # ---- Step 13: Discord + persist notification row --------- #
            sent = send_scan_complete_notification(
                webhook_url=None,
                program_name=program.name,
                scope_target=scope.target,
                metrics=metrics,
                new_subdomains=new_subdomains_sample,
            )
            if sent:
                sent_at = datetime.now(timezone.utc)
                self.notification_repo.create(
                    db,
                    program_id=program.id,
                    scope_id=scope.id,
                    channel="WEBHOOK",
                    sent=True,
                    sent_at=sent_at,
                )

            # ---- Step 14: Chain DNS scan ----------------------------- #
            # Enqueue a DNS scan for the same scope so the pipeline
            # continues automatically after subdomain discovery — unless the
            # user asked to pause/stop at this phase boundary.
            if metrics.unique_count > 0:
                signal = self.check_control(scan_run_id)
                if signal == "STOP":
                    self.logger.info("Scan %s stopped before chaining DNS", scan_run_id)
                    self.mark_cancelled(scan_run_id)
                    return
                if signal == "PAUSE":
                    self.logger.info("Scan %s paused before chaining DNS", scan_run_id)
                    self.mark_paused(scan_run_id, resume_state={"pending_chain": "DNS"})
                    return
                try:
                    self._chain_dns_scan(db, program.id, scope.id)
                except Exception as chain_exc:
                    self.logger.warning(
                        "Failed to chain DNS scan after subdomain scan %s: %s",
                        scan_run_id, chain_exc,
                    )

        except Exception as exc:
            self.logger.exception("Subdomain scan %s failed: %s", scan_run_id, exc)
            self.mark_failed(scan_run_id, str(exc))
        finally:
            if scan_run is not None:
                try:
                    release_scope_lock(scan_run.scope_id)
                except Exception:
                    pass
            db.close()

    # ------------------------------------------------------------------ #
    # Generic tool runner                                                   #
    # ------------------------------------------------------------------ #

    def _run_tool(
        self,
        db,
        scan_run,
        scope,
        program,
        metrics: ScanMetrics,
        raw_dir: Path,
        source_map: dict[str, set[str]],
        tool_name: str,
        runner,
        raw_attr: str,
        count_attr: str,
    ) -> None:
        """Run one enumeration tool, save its raw output, filter in-scope, and
        accumulate results into *source_map*.  A single tool failure is isolated
        — it logs an error and returns without raising.
        """
        exec_rec = self._create_tool_execution(
            db, scan_run.id, tool_name,
            f"{tool_name} -d {scope.target}",
        )
        try:
            raw: list[str] = runner.run(scope.target)
            self.storage_service.save_lines_artifact(raw_dir, f"{tool_name}.txt", raw)
            filtered = filter_in_scope(raw, scope.target)
            setattr(metrics, raw_attr, len(raw))
            setattr(metrics, count_attr, len(filtered))
            for sub in filtered:
                source_map.setdefault(sub, set()).add(tool_name)
            self._finalize_tool_execution(
                db, exec_rec, ToolExecutionStatus.COMPLETED,
                raw_records_found=len(raw),
                records_found=len(filtered),
            )
            self.logger.info(
                "%s: %d raw → %d in-scope (%d filtered out)",
                tool_name, len(raw), len(filtered), len(raw) - len(filtered),
            )
        except RuntimeError as exc:
            self._finalize_tool_execution(
                db, exec_rec, ToolExecutionStatus.FAILED, error_message=str(exc)
            )
            self.logger.error("%s failed: %s", tool_name, exc)

    # ------------------------------------------------------------------ #
    # Disk-based merge                                                      #
    # ------------------------------------------------------------------ #

    def _merge_raw_files(
        self,
        raw_dir: Path,
        processed_path: Path,
        scope_target: str,
    ) -> list[str]:
        """Merge all per-tool raw files into processed/subdomains.txt using
        disk-based sort -u to avoid holding 100 k+ entries in memory.

        Returns the sorted unique in-scope subdomain list (read back from disk
        in one streaming pass — small enough for upsert batching at 50 k rows).
        """
        raw_files = [
            raw_dir / name
            for name in (
                "subfinder.txt", "assetfinder.txt", "knockpy.txt",
                "dnsgen.txt", "chaos.txt", "crtsh.txt", "findomain.txt",
            )
            if (raw_dir / name).exists() and (raw_dir / name).stat().st_size > 0
        ]

        if not raw_files:
            processed_path.write_text("", encoding="utf-8")
            return []

        root = scope_target.strip().lower()
        if root.startswith("*."):
            root = root[2:]

        # Use a temporary merged+sorted file, then filter in-scope back to
        # processed_path. This keeps the pipeline fully disk-bound.
        merged_tmp = processed_path.parent / "_merge_tmp.txt"
        try:
            with merged_tmp.open("w", encoding="utf-8") as fout:
                subprocess.run(
                    ["sort", "-u", "--", *[str(f) for f in raw_files]],
                    stdout=fout,
                    check=False,
                )

            # Filter in-scope and normalise while streaming from disk
            subdomains: list[str] = []
            with (
                merged_tmp.open("r", encoding="utf-8", errors="replace") as fin,
                processed_path.open("w", encoding="utf-8") as fout,
            ):
                first = True
                for line in fin:
                    name = _normalise(line)
                    if not name:
                        continue
                    if not _in_scope(name, root):
                        continue
                    if not first:
                        fout.write("\n")
                    fout.write(name)
                    first = False
                    subdomains.append(name)
        finally:
            merged_tmp.unlink(missing_ok=True)

        return subdomains

    # ------------------------------------------------------------------ #
    # Bulk DB operations                                                    #
    # ------------------------------------------------------------------ #

    def _bulk_upsert_subdomains(
        self,
        db,
        scan_run_id: uuid.UUID,
        scope_id: uuid.UUID,
        program_id: uuid.UUID,
        subdomains: list[str],
        source_map: dict[str, str],
        now: datetime,
        metrics: ScanMetrics,
    ) -> list[str]:
        """Batch-upsert all subdomains; write per-tool source rows for new ones.

        Returns a bounded sample of newly discovered subdomain strings for the
        Discord notification.
        """
        new_subdomains_sample: list[str] = []
        diff_handle = None
        diff_path = (
            self.storage_service.get_diff_path_by_id(program_id, scope_id)
            / f"{now.strftime('%Y-%m-%dT%H-%M-%S')}-new.txt"
        )
        wrote_diff_line = False

        try:
            for start in range(0, len(subdomains), DB_UPSERT_BATCH_SIZE):
                batch = subdomains[start:start + DB_UPSERT_BATCH_SIZE]
                rows: list[dict[str, Any]] = [
                    {
                        "id": uuid.uuid4(),
                        "scope_id": scope_id,
                        "program_id": program_id,
                        "subdomain": sub,
                        "source": source_map.get(sub, ""),
                        "first_seen": now,
                        "last_seen": now,
                        "created_at": now,
                        "updated_at": now,
                    }
                    for sub in batch
                ]

                new_rows, existing_rows = self.subdomain_repo.bulk_upsert_staged(db, rows)
                metrics.new_count += len(new_rows)
                metrics.existing_count += len(existing_rows)

                # Upsert Asset rows for every subdomain in this batch (new + existing)
                all_batch_rows = new_rows + existing_rows
                if all_batch_rows:
                    sub_to_id: dict[str, uuid.UUID] = {r["subdomain"]: r["id"] for r in all_batch_rows}
                    asset_rows = [
                        {
                            "id": uuid.uuid4(),
                            "program_id": program_id,
                            "scope_id": scope_id,
                            "asset_value": sub,
                            "source": source_map.get(sub, ""),
                            "first_seen": now,
                            "last_seen": now,
                            "created_at": now,
                            "updated_at": now,
                        }
                        for sub in (r["subdomain"] for r in all_batch_rows)
                    ]
                    asset_value_to_id = self.asset_repo.bulk_upsert_subdomains(db, asset_rows)

                    # Back-fill subdomain.asset_id for any row that doesn't have one yet.
                    # Use a VALUES join to avoid building dynamic SQL from user-controlled data.
                    backfill_pairs = [
                        (sub_to_id[sub], asset_id)
                        for sub, asset_id in asset_value_to_id.items()
                        if sub in sub_to_id
                    ]
                    if backfill_pairs:
                        # Use CAST(...) instead of ::uuid — psycopg2 treats the second
                        # colon in :param::type as another bind parameter, causing a
                        # SyntaxError.
                        values_clause = ", ".join(
                            f"(CAST(:sid_{i} AS uuid), CAST(:aid_{i} AS uuid))"
                            for i in range(len(backfill_pairs))
                        )
                        params: dict[str, Any] = {}
                        for i, (sid, aid) in enumerate(backfill_pairs):
                            params[f"sid_{i}"] = str(sid)
                            params[f"aid_{i}"] = str(aid)
                        db.execute(
                            text(
                                f"""
                                UPDATE subdomains s
                                SET asset_id = m.asset_id
                                FROM (VALUES {values_clause}) AS m(subdomain_id, asset_id)
                                WHERE s.id = m.subdomain_id
                                  AND s.asset_id IS NULL
                                """
                            ),
                            params,
                        )
                        db.commit()

                if new_rows:
                    if diff_handle is None:
                        diff_handle = diff_path.open("w", encoding="utf-8")
                    for row in new_rows:
                        if wrote_diff_line:
                            diff_handle.write("\n")
                        diff_handle.write(row["subdomain"])
                        wrote_diff_line = True
                        if len(new_subdomains_sample) < NOTIFICATION_SAMPLE_LIMIT:
                            new_subdomains_sample.append(row["subdomain"])

                # Source rows only for newly inserted subdomains
                id_map: dict[str, uuid.UUID] = {r["subdomain"]: r["id"] for r in new_rows}
                source_records: list[dict[str, Any]] = []
                for sub in batch:
                    sub_id = id_map.get(sub)
                    if not sub_id:
                        continue
                    # source_map[sub] is already a comma-separated sorted string
                    for tool in source_map.get(sub, "").split(","):
                        tool = tool.strip()
                        if tool:
                            source_records.append({
                                "id": uuid.uuid4(),
                                "subdomain_id": sub_id,
                                "scan_run_id": scan_run_id,
                                "tool_name": tool,
                                "created_at": now,
                            })

                self.subdomain_source_repo.bulk_insert_sources_staged(db, source_records)
        finally:
            if diff_handle is not None:
                diff_handle.close()

        if wrote_diff_line:
            self.logger.info("Diff written: %s", diff_path.name)

        self.logger.info(
            "DB upsert: %d new, %d existing", metrics.new_count, metrics.existing_count
        )
        return new_subdomains_sample

    # ------------------------------------------------------------------ #
    # ToolExecution lifecycle helpers                                        #
    # ------------------------------------------------------------------ #

    def _load_scan_data(self, db, scan_run_id: uuid.UUID):
        from backend.services.scan_run_service import ScanRunService
        scan_run_service = ScanRunService()
        scan_run = scan_run_service.get_scan_run(db=db, scan_run_id=scan_run_id)
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
        self,
        db,
        tool_execution,
        status: ToolExecutionStatus,
        output_path: str | None = None,
        error_message: str | None = None,
        raw_records_found: int = 0,
        records_found: int = 0,
    ) -> None:
        self.tool_execution_repo.update(
            db,
            tool_execution,
            status=status.value,
            output_path=output_path,
            error_message=error_message,
            raw_records_found=raw_records_found,
            records_found=records_found,
            finished_at=datetime.now(timezone.utc),
        )

    def _chain_dns_scan(self, db, program_id: uuid.UUID, scope_id: uuid.UUID) -> None:
        """Create a DNS ScanRun and enqueue run_dns_scan for automatic chaining."""
        from backend.services.scan_run_service import ScanRunService
        from database.models.enums import ScanStatus, ScanType

        svc = ScanRunService()
        dns_scan = svc.create_scan_run(
            db=db,
            program_id=program_id,
            scope_id=scope_id,
            scan_type=ScanType.DNS.value,
            worker_name="dns_worker",
            status=ScanStatus.PENDING.value,
        )
        celery_app.send_task(
            "workers.dns.dns_worker.run_dns_scan",
            args=[str(dns_scan.id)],
            countdown=2,
        )
        self.logger.info("Chained DNS scan %s for scope %s", dns_scan.id, scope_id)

    def _update_scan_metrics(self, db, scan_run_id: uuid.UUID, metrics: ScanMetrics) -> None:
        db.execute(
            update(ScanRun)
            .where(ScanRun.id == scan_run_id)
            .values(
                subfinder_count=metrics.subfinder_count,
                assetfinder_count=metrics.assetfinder_count,
                knockpy_count=metrics.knockpy_count,
                dnsgen_count=metrics.dnsgen_count,
                chaos_count=metrics.chaos_count,
                crtsh_count=metrics.crtsh_count,
                findomain_count=metrics.findomain_count,
                merged_count=metrics.merged_count,
                unique_count=metrics.unique_count,
                new_count=metrics.new_count,
                existing_count=metrics.existing_count,
            )
        )
        db.commit()


# ------------------------------------------------------------------ #
# Normalisation helpers (module-level for speed)                        #
# ------------------------------------------------------------------ #

def _normalise(line: str) -> str:
    """Lowercase, strip whitespace, remove wildcard prefix, blank-out invalids."""
    name = line.strip().lower()
    if name.startswith("*."):
        name = name[2:]
    if not name or "." not in name:
        return ""
    return name


def _in_scope(name: str, root: str) -> bool:
    return name == root or name.endswith("." + root)


# ------------------------------------------------------------------ #
# Celery task                                                           #
# ------------------------------------------------------------------ #

@celery_app.task(name="workers.subdomain.subdomain_worker.run_subdomain_scan", bind=True)
def run_subdomain_scan(self, scan_run_id: str) -> None:
    SubdomainScanWorker().run_scan(scan_run_id)
