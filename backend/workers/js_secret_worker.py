"""JavaScript Secret Discovery worker — Phase 6.2.

ONE responsibility: analyse the JS files already stored in ``js_files`` and build
a centralized, deduplicated Secret Inventory.

Pipeline (scan_type = JS_SECRET)::

    stream js_files (batched, keyset — constant memory)
        └─ per batch:
             download JS → /tmp temp dir
             ├─ SecretFinder (local files)  ┐
             ├─ Mantra (JS URLs)            ├─ run in parallel, isolated failure
             └─ Nuclei http/exposures (URLs)┘
             classify → normalize → fingerprint → merge (union tools) → dedup
             bulk-upsert js_secrets (ON CONFLICT fingerprint → union discovery_tools)
             attribute per-tool sources
             increment host/subdomain secret counters (new rows only)
             DELETE downloaded JS + scratch (guaranteed, even on error)
             Discord notify for newly discovered secrets
    persist merged artifact → update ScanRun metrics

Secrets are stored **unmasked** (analysts must verify/report). Nuclei is used
ONLY with http/exposures/ templates — never for vulnerability scanning.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import update

from backend.celery_app import celery_app
from backend.queues.redis_client import release_scope_lock
from backend.services.program_service import ProgramService
from backend.services.scope_service import ScopeService
from backend.services.storage_service import StorageService
from database.models.enums import ToolExecutionStatus
from database.models.scan_run import ScanRun
from repositories.host_repository import HostRepository
from repositories.js_file_repository import JsFileRepository
from repositories.js_secret_repository import JsSecretRepository
from repositories.subdomain_repository import SubdomainRepository
from repositories.tool_execution_repository import ToolExecutionRepository
from tools.common.scope_filter import host_of_url, is_host_in_scope
from tools.common.secret_utils import (
    classify_secret_type,
    fingerprint,
    is_probably_valid,
    normalize_secret,
    severity_for,
)
from tools.javascript.mantra import MantraRunner
from tools.javascript.nuclei_exposures import NucleiExposuresRunner
from tools.javascript.secretfinder import SecretFinderRunner
from tools.js_endpoint.js_download_manager import JsDownloadManager
from workers.base.base_worker import BaseWorker

JS_BATCH_SIZE = int(os.getenv("JS_SECRET_BATCH_SIZE", "150"))
DB_BATCH_SIZE = 5_000

SECRETFINDER = "SECRETFINDER"
MANTRA = "MANTRA"
NUCLEI = "NUCLEI_EXPOSURES"


@dataclass
class SecretMetrics:
    js_total: int = 0
    js_processed: int = 0
    js_failed: int = 0
    secretfinder_count: int = 0   # raw findings per tool (pre-merge)
    mantra_count: int = 0
    nuclei_count: int = 0
    total_secrets: int = 0        # unique secrets in scope after this run
    new_secrets: int = 0
    tool_errors: dict = field(default_factory=dict)


class JsSecretWorker(BaseWorker):
    def __init__(self) -> None:
        super().__init__(name="js_secret_worker")
        self.program_service = ProgramService()
        self.scope_service = ScopeService()
        self.storage_service = StorageService()
        self.secret_repo = JsSecretRepository()
        self.js_repo = JsFileRepository()
        self.host_repo = HostRepository()
        self.subdomain_repo = SubdomainRepository()
        self.tool_execution_repo = ToolExecutionRepository()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run_scan(self, scan_run_id: str) -> None:
        db = self.get_db()
        scan_run = None
        metrics = SecretMetrics()
        started = datetime.now(timezone.utc)
        tool_raw_counts = {SECRETFINDER: 0, MANTRA: 0, NUCLEI: 0}

        try:
            scan_run_uuid = uuid.UUID(scan_run_id)
            scan_run, program, scope = self._load_scan_data(db, scan_run_uuid)
            self.mark_running(scan_run_id)
            self._scope_target = scope.target

            self.storage_service.init_scope_directories_by_id(program.id, scope.id)
            sec_raw = self.storage_service.get_raw_path_by_id(program.id, scope.id, "secrets")
            sec_proc = self.storage_service.get_processed_path_by_id(program.id, scope.id, "secrets")

            metrics.js_total = self.js_repo.count_scope_js(db, scope.id)
            self.logger.info("JS secret discovery: %d JS files in scope %s",
                             metrics.js_total, scope.id)
            if metrics.js_total == 0:
                self._update_scan_metrics(db, scan_run.id, metrics, tool_raw_counts)
                self.mark_completed(scan_run_id, records_found=0)
                return

            host_map = self.host_repo.map_hostnames_to_ids(db, scope.id)
            tools = self._build_tools()
            available = {name: t.health_check() for name, t in tools.items()}
            for name, ok in available.items():
                if not ok:
                    self.logger.warning("Scanner %s unavailable — skipping it", name)

            now = datetime.now(timezone.utc)

            batch: list[tuple[uuid.UUID, str, uuid.UUID | None]] = []
            for js_id, js_url, js_host_id in self.js_repo.iter_scope_js(
                db, scope.id, batch_size=JS_BATCH_SIZE
            ):
                batch.append((js_id, js_url, js_host_id))
                if len(batch) >= JS_BATCH_SIZE:
                    self._process_batch(db, program, scope, host_map, tools, available,
                                        batch, now, metrics, tool_raw_counts, sec_raw)
                    batch = []
            if batch:
                self._process_batch(db, program, scope, host_map, tools, available,
                                    batch, now, metrics, tool_raw_counts, sec_raw)

            metrics.total_secrets = self.secret_repo.count_for_scope(db, scope.id)
            self._persist_run_artifact(db, sec_proc, scope.id)
            self._record_tool_executions(db, scan_run.id, tool_raw_counts, metrics)
            self._update_scan_metrics(db, scan_run.id, metrics, tool_raw_counts)
            self.mark_completed(scan_run_id, records_found=metrics.new_secrets)

            self.logger.info(
                "JS secret discovery %s done — js=%d (ok=%d fail=%d) secrets total=%d new=%d",
                scan_run_id, metrics.js_total, metrics.js_processed, metrics.js_failed,
                metrics.total_secrets, metrics.new_secrets,
            )

            from workers.notification.discord_worker import send_js_secret_summary
            duration = (datetime.now(timezone.utc) - started).total_seconds()
            send_js_secret_summary(
                webhook_url=None, program_name=program.name, scope_target=scope.target,
                metrics=metrics, duration_seconds=duration,
            )

        except Exception as exc:
            self.logger.exception("JS secret scan %s failed: %s", scan_run_id, exc)
            self.mark_failed(scan_run_id, str(exc))
        finally:
            if scan_run is not None:
                try:
                    release_scope_lock(scan_run.scope_id)
                except Exception:
                    pass
            db.close()

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------

    def _process_batch(self, db, program, scope, host_map, tools, available,
                       batch, now, metrics, tool_raw_counts, sec_raw) -> None:
        js_items = [(url, jid) for jid, url, _ in batch]
        js_urls = [url for _, url, _ in batch]

        with JsDownloadManager() as dl:
            downloaded, failed = dl.download_batch(js_items)
            metrics.js_failed += len(failed)
            if failed:
                self.logger.info("JS batch: %d downloaded, %d failed",
                                 len(downloaded), len(failed))
            if not downloaded and not js_urls:
                return

            # (local_path, js_url) pairs for file-based scanners (SecretFinder).
            local_files = [(d.path, d.url) for d in downloaded]
            metrics.js_processed += len(downloaded)

            per_tool = self._run_scanners(tools, available, local_files, js_urls,
                                          metrics, tool_raw_counts)
            merged = self._merge(per_tool, scope.target)

        # temp JS deleted (context manager) — persist from memory.
        if merged:
            self._persist_secrets(db, program, scope, host_map, merged, now, metrics)

    def _run_scanners(self, tools, available, local_files, js_urls,
                      metrics, tool_raw_counts) -> dict[str, list]:
        """Run every available scanner in parallel. Returns {tool: [RawSecret]}."""
        results: dict[str, list] = {}

        def _run(name: str):
            t0 = time.monotonic()
            tool = tools[name]
            if name == SECRETFINDER:
                found = tool.run(local_files)
            else:  # Mantra / Nuclei take URLs
                found = tool.run(js_urls)
            self.logger.info("Tool=%s inputs=%d raw_secrets=%d status=SUCCESS time=%dms",
                             name, len(local_files) if name == SECRETFINDER else len(js_urls),
                             len(found), int((time.monotonic() - t0) * 1000))
            return name, found

        runnable = [n for n in tools if available.get(n)]
        with ThreadPoolExecutor(max_workers=max(1, len(runnable))) as pool:
            futures = [pool.submit(_run, n) for n in runnable]
            for fut in futures:
                try:
                    name, found = fut.result()
                    results[name] = found
                    tool_raw_counts[name] += len(found)
                except Exception as exc:  # one scanner failing never kills the batch
                    self.logger.warning("Scanner raised during batch: %s", exc)

        metrics.secretfinder_count += len(results.get(SECRETFINDER, []))
        metrics.mantra_count += len(results.get(MANTRA, []))
        metrics.nuclei_count += len(results.get(NUCLEI, []))
        return results

    def _merge(self, per_tool: dict[str, list], scope_target: str) -> dict[str, dict]:
        """Classify, normalize, fingerprint, and merge secrets across scanners.

        Returns ``{fingerprint: {...secret fields..., tools: set}}``. Out-of-scope
        (by the JS URL host) and junk/placeholder values are dropped.
        """
        merged: dict[str, dict] = {}
        for tool_name, findings in per_tool.items():
            for rs in findings:
                stype = classify_secret_type(rs.raw_type, rs.value)
                if not is_probably_valid(rs.value, stype):
                    continue
                normalized = normalize_secret(rs.value)
                if not normalized:
                    continue
                # Scope gate on the originating JS file host.
                js_host = host_of_url(rs.js_url) if rs.js_url else None
                if scope_target and js_host and not is_host_in_scope(js_host, scope_target):
                    continue
                fp = fingerprint(stype, normalized)
                entry = merged.get(fp)
                if entry is None:
                    merged[fp] = {
                        "fingerprint": fp,
                        "secret_type": stype,
                        "secret_value": rs.value,          # UNMASKED, as discovered
                        "normalized_secret": normalized,
                        "severity": severity_for(stype),
                        "confidence": rs.confidence,
                        "js_url": rs.js_url,
                        "host": js_host,
                        "tools": {tool_name},
                    }
                else:
                    entry["tools"].add(tool_name)
                    entry["confidence"] = max(entry["confidence"], rs.confidence)
        return merged

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_secrets(self, db, program, scope, host_map, merged, now, metrics) -> None:
        items = list(merged.items())
        js_url_to_id = {}  # resolve js_file_id lazily by URL if needed

        for start in range(0, len(items), DB_BATCH_SIZE):
            chunk = items[start:start + DB_BATCH_SIZE]
            rows: list[dict] = []
            fp_to_tools: dict[str, set[str]] = {}
            for fp, data in chunk:
                host = data.get("host")
                host_id = host_map.get(host) if host else None
                fp_to_tools[fp] = data["tools"]
                rows.append({
                    "id": uuid.uuid4(),
                    "program_id": program.id,
                    "scope_id": scope.id,
                    "host_id": host_id,
                    "js_file_id": None,
                    "js_file_url": data.get("js_url"),
                    "host": host[:255] if host else None,
                    "secret_type": data["secret_type"],
                    "secret_value": data["secret_value"],
                    "normalized_secret": data["normalized_secret"],
                    "fingerprint": fp,
                    "confidence": int(data.get("confidence", 50)),
                    "severity": data["severity"],
                    "discovery_tools": sorted(data["tools"]),
                    "first_seen": now,
                    "last_seen": now,
                    "created_at": now,
                    "updated_at": now,
                })

            new_rows, existing_rows = self.secret_repo.bulk_upsert(db, rows)
            metrics.new_secrets += len(new_rows)

            # Per-tool source attribution.
            id_by_fp = {r["fingerprint"]: r["id"] for r in (new_rows + existing_rows)}
            source_rows = []
            for fp, tools in fp_to_tools.items():
                sid = id_by_fp.get(fp)
                if not sid:
                    continue
                for tool in tools:
                    source_rows.append({"secret_id": sid, "tool_name": tool})
            self.secret_repo.bulk_insert_sources(db, source_rows)

            # Counters — only NEW secrets, rolled up per host + subdomain.
            host_deltas: dict[uuid.UUID, int] = {}
            name_deltas: dict[str, int] = {}
            for r in new_rows:
                hid = r.get("host_id")
                if hid:
                    host_deltas[hid] = host_deltas.get(hid, 0) + 1
                hn = r.get("host")
                if hn:
                    name_deltas[hn] = name_deltas.get(hn, 0) + 1
            self.host_repo.bulk_increment_secret_counts(db, host_deltas)
            self.subdomain_repo.bulk_increment_secret_counts(db, scope.id, name_deltas)

            # Discord: notify for each NEW secret (severity-routed design).
            self._notify_new_secrets(program, scope, chunk, id_by_fp, new_rows)

    def _notify_new_secrets(self, program, scope, chunk, id_by_fp, new_rows) -> None:
        new_ids = {r["id"] for r in new_rows}
        by_fp = {fp: data for fp, data in chunk}
        from workers.notification.discord_worker import send_secret_notification
        for fp, sid in id_by_fp.items():
            if sid not in new_ids:
                continue
            data = by_fp.get(fp)
            if not data:
                continue
            try:
                send_secret_notification(
                    webhook_url=None,
                    program_name=program.name,
                    scope_target=scope.target,
                    host=data.get("host"),
                    secret_type=data["secret_type"],
                    severity=data["severity"],
                    js_url=data.get("js_url"),
                    tools=sorted(data["tools"]),
                    secret_value=data["secret_value"],
                )
            except Exception:
                pass  # notifications must never break the scan

    def _persist_run_artifact(self, db, sec_proc: Path, scope_id: uuid.UUID) -> None:
        target = sec_proc / "merged_secrets.json"
        with target.open("w", encoding="utf-8") as fh:
            offset = 0
            page = 5_000
            while True:
                rows = self.secret_repo.list_secrets(
                    db, scope_id=scope_id, offset=offset, limit=page, sort_by="created_at",
                )
                if not rows:
                    break
                for s in rows:
                    fh.write(json.dumps({
                        "secret_type": s.secret_type, "severity": s.severity,
                        "secret_value": s.secret_value, "host": s.host,
                        "js_file_url": s.js_file_url, "discovery_tools": s.discovery_tools,
                    }) + "\n")
                offset += len(rows)
                if len(rows) < page:
                    break

    # ------------------------------------------------------------------
    # Metrics / helpers
    # ------------------------------------------------------------------

    def _record_tool_executions(self, db, scan_run_id, tool_raw_counts, metrics) -> None:
        for name, raw in tool_raw_counts.items():
            rec = self.tool_execution_repo.create(
                db, scan_run_id=scan_run_id, tool_name=name.lower(),
                command=f"{name.lower()} <js files>",
                status=ToolExecutionStatus.RUNNING.value,
                started_at=datetime.now(timezone.utc),
            )
            status = (ToolExecutionStatus.FAILED if name in metrics.tool_errors
                      else ToolExecutionStatus.COMPLETED)
            self.tool_execution_repo.update(
                db, rec, status=status.value,
                error_message=metrics.tool_errors.get(name),
                raw_records_found=raw, records_found=raw,
                finished_at=datetime.now(timezone.utc),
            )

    def _update_scan_metrics(self, db, scan_run_id, metrics, tool_raw_counts) -> None:
        db.execute(
            update(ScanRun).where(ScanRun.id == scan_run_id).values(
                secretfinder_count=tool_raw_counts.get(SECRETFINDER, 0),
                mantra_count=tool_raw_counts.get(MANTRA, 0),
                nuclei_exposures_count=tool_raw_counts.get(NUCLEI, 0),
                js_processed_count=metrics.js_processed,
                js_failed_count=metrics.js_failed,
                total_secrets_count=metrics.total_secrets,
                new_secrets_count=metrics.new_secrets,
            )
        )
        db.commit()

    def _build_tools(self) -> dict:
        """Instantiate every secret scanner. Register new tools here only."""
        return {
            SECRETFINDER: SecretFinderRunner(timeout=120),
            MANTRA: MantraRunner(timeout=600),
            NUCLEI: NucleiExposuresRunner(timeout=1800),
        }

    def _load_scan_data(self, db, scan_run_id: uuid.UUID):
        from backend.services.scan_run_service import ScanRunService
        svc = ScanRunService()
        scan_run = svc.get_scan_run(db=db, scan_run_id=scan_run_id)
        program = self.program_service.get_program(db=db, program_id=scan_run.program_id)
        scope = self.scope_service.get_scope(db=db, scope_id=scan_run.scope_id)
        return scan_run, program, scope


@celery_app.task(name="workers.js_secret_worker.run_js_secret_scan", bind=True)
def run_js_secret_scan(self, scan_run_id: str) -> None:
    JsSecretWorker().run_scan(scan_run_id)
