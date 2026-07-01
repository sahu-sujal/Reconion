"""JavaScript Endpoint Discovery worker — Phase 6.1.

ONE responsibility: extract every endpoint from the JS files already stored in
the ``js_files`` table and build a single unified, deduplicated Endpoint
Inventory of fully-qualified absolute URLs.

Pipeline (scan_type = JS_ENDPOINT)::

    stream js_files (batched, constant memory)
        └─ per batch:
             download JS → /tmp temp dir
             ├─ LinkFinder   ┐
             ├─ XNLinkFinder ├─ run in parallel, per file
             └─ JSluice (AST)┘
             merge raw hits → resolve against JS URL → normalize → dedupe
             bulk-upsert endpoints (union discovery_tools on conflict)
             attribute per-tool sources
             increment host/subdomain endpoint counters (new rows only)
             DELETE downloaded JS + tool scratch (guaranteed, even on error)
    persist merged artifacts → update ScanRun metrics → Discord

Design notes:
  * Extractors implement a common interface (``EndpointToolBase``); adding a new
    one (Mantra, custom AST parser) is a one-line change to ``EXTRACTORS`` — the
    worker body never changes, and the DB schema is already extractor-agnostic.
  * Tool failures are isolated: one extractor (or one file) failing never aborts
    the batch or the scan. JSluice failing on a file falls back to per-file
    retry, then is skipped.
  * Downloaded JavaScript is never kept — cleanup runs in ``finally`` for every
    batch, so no JS source remains on disk after processing.
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
from database.models.enums import DiscoverySource, ToolExecutionStatus
from database.models.scan_run import ScanRun
from repositories.endpoint_repository import EndpointRepository
from repositories.host_repository import HostRepository
from repositories.js_file_repository import JsFileRepository
from repositories.subdomain_repository import SubdomainRepository
from repositories.tool_execution_repository import ToolExecutionRepository
from tools.common.endpoint_utils import resolve_endpoint
from tools.common.scope_filter import is_host_in_scope
from tools.javascript.jsluice import JsluiceRunner
from tools.js_endpoint.js_download_manager import JsDownloadManager
from tools.js_endpoint.linkfinder_runner import LinkFinderRunner
from tools.js_endpoint.xnlinkfinder_runner import XnLinkFinderRunner
from workers.base.base_worker import BaseWorker

# How many JS files to download + process per batch. Keeps memory + temp-disk
# bounded regardless of total inventory size (200k+ files supported).
JS_BATCH_SIZE = int(os.getenv("JS_ENDPOINT_BATCH_SIZE", "300"))
# Endpoints are upserted in chunks of this size.
DB_BATCH_SIZE = 10_000

# The extractor registry — order is irrelevant, all run in parallel. Add future
# tools here; the worker and schema need no other change.
LINKFINDER = "LINKFINDER"
XNLINKFINDER = "XNLINKFINDER"
JSLUICE = "JSLUICE"


@dataclass
class EndpointMetrics:
    js_total: int = 0            # JS files in the inventory for this scope
    js_processed: int = 0        # JS files successfully downloaded + parsed
    js_failed: int = 0           # JS files that could not be downloaded
    linkfinder_count: int = 0    # raw hits emitted by each tool (pre-merge)
    xnlinkfinder_count: int = 0
    jsluice_count: int = 0
    total_endpoints: int = 0     # unique endpoints upserted this run
    new_endpoints: int = 0
    tool_errors: dict = field(default_factory=dict)


class JsEndpointWorker(BaseWorker):
    def __init__(self) -> None:
        super().__init__(name="js_endpoint_worker")
        self.program_service = ProgramService()
        self.scope_service = ScopeService()
        self.storage_service = StorageService()
        self.endpoint_repo = EndpointRepository()
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
        metrics = EndpointMetrics()
        started = datetime.now(timezone.utc)

        # Per-tool aggregate raw counts for tool_executions (across all batches).
        tool_raw_counts = {LINKFINDER: 0, XNLINKFINDER: 0, JSLUICE: 0}

        try:
            scan_run_uuid = uuid.UUID(scan_run_id)
            scan_run, program, scope = self._load_scan_data(db, scan_run_uuid)
            self.mark_running(scan_run_id)

            self.storage_service.init_scope_directories_by_id(program.id, scope.id)
            ep_raw = self.storage_service.get_raw_path_by_id(program.id, scope.id, "endpoints")
            ep_proc = self.storage_service.get_processed_path_by_id(program.id, scope.id, "endpoints")

            metrics.js_total = self.js_repo.count_scope_js(db, scope.id)
            self.logger.info("JS endpoint discovery: %d JS files in scope %s",
                             metrics.js_total, scope.id)
            if metrics.js_total == 0:
                self._update_scan_metrics(db, scan_run.id, metrics, tool_raw_counts)
                self.mark_completed(scan_run_id, records_found=0)
                return

            host_map = self.host_repo.map_hostnames_to_ids(db, scope.id)

            # Scope target used to drop out-of-scope endpoints at merge time —
            # a JS file can reference third-party/CDN hosts (cdn.example.com,
            # googleapis.com) that are out of scope and can't be reported.
            self._scope_target = scope.target

            # Build extractor instances once (they resolve their binaries at init).
            extractors = self._build_extractors(scope.target)
            # Record which extractors are actually runnable up front.
            available = {name: e.health_check() for name, e in extractors.items()}
            for name, ok in available.items():
                if not ok:
                    self.logger.warning("Extractor %s unavailable — skipping it", name)

            now = datetime.now(timezone.utc)

            # Resume support: continue after the last JS id processed in a prior
            # run (keyset cursor — commit-safe and stable). resume_state carries
            # the cumulative counts so the scan report stays correct across
            # pause/resume.
            resume = scan_run.resume_state or {}
            after_id = None
            if resume.get("last_js_id"):
                after_id = uuid.UUID(resume["last_js_id"])
                metrics.js_processed = int(resume.get("js_processed", 0) or 0)
                metrics.js_failed = int(resume.get("js_failed", 0) or 0)
                metrics.new_endpoints = int(resume.get("new_endpoints", 0) or 0)
                for k in (LINKFINDER, XNLINKFINDER, JSLUICE):
                    tool_raw_counts[k] = int(resume.get(f"raw_{k}", 0) or 0)
                self.logger.info("Resuming JS endpoint scan %s after JS id %s",
                                 scan_run_id, after_id)

            # Iterate JS files in id-ordered batches (keyset pagination).
            last_id = after_id
            batch: list[tuple[str, uuid.UUID | None, uuid.UUID | None]] = []
            for js_id, js_url, js_host_id in self.js_repo.iter_scope_js(
                db, scope.id, batch_size=JS_BATCH_SIZE, after_id=after_id,
            ):
                last_id = js_id
                batch.append((js_url, js_id, js_host_id))
                if len(batch) >= JS_BATCH_SIZE:
                    self._process_batch(
                        db, program.id, scope.id, host_map, extractors, available,
                        batch, now, metrics, tool_raw_counts, ep_raw,
                    )
                    batch = []
                    # Safe boundary: react to a pause/stop between batches.
                    decision = self._handle_batch_control(
                        scan_run_id, last_id, metrics, tool_raw_counts,
                    )
                    if decision is not None:
                        return  # paused or stopped — checkpoint already saved
            if batch:
                self._process_batch(
                    db, program.id, scope.id, host_map, extractors, available,
                    batch, now, metrics, tool_raw_counts, ep_raw,
                )

            # Total unique endpoints in scope after this run.
            metrics.total_endpoints = self.endpoint_repo.count_for_scope(db, scope.id)

            self._persist_run_artifacts(db, ep_proc, scope.id)
            self._record_tool_executions(db, scan_run.id, tool_raw_counts, metrics)
            self._update_scan_metrics(db, scan_run.id, metrics, tool_raw_counts)
            self.scan_run_service.update_scan_run(
                db=db, scan_run_id=scan_run_id, clear_resume_state=True,
            )
            self.mark_completed(scan_run_id, records_found=metrics.new_endpoints)

            self.logger.info(
                "JS endpoint discovery %s done — js=%d (ok=%d fail=%d) "
                "endpoints total=%d new=%d",
                scan_run_id, metrics.js_total, metrics.js_processed,
                metrics.js_failed, metrics.total_endpoints, metrics.new_endpoints,
            )

            from workers.notification.discord_worker import send_js_endpoint_notification
            duration = (datetime.now(timezone.utc) - started).total_seconds()
            send_js_endpoint_notification(
                webhook_url=None,
                program_name=program.name,
                scope_target=scope.target,
                metrics=metrics,
                duration_seconds=duration,
            )

        except Exception as exc:
            self.logger.exception("JS endpoint scan %s failed: %s", scan_run_id, exc)
            self.mark_failed(scan_run_id, str(exc))
        finally:
            if scan_run is not None:
                try:
                    release_scope_lock(scan_run.scope_id)
                except Exception:
                    pass
            db.close()

    def _handle_batch_control(
        self,
        scan_run_id: str,
        last_js_id: uuid.UUID | None,
        metrics: "EndpointMetrics",
        tool_raw_counts: dict[str, int],
    ) -> str | None:
        """React to a pause/stop signal between JS batches.

        Returns ``"PAUSE"`` / ``"STOP"`` if the scan should end here (checkpoint
        or cancellation already recorded), or ``None`` to keep processing.
        """
        signal = self.check_control(scan_run_id)
        if signal not in ("PAUSE", "STOP"):
            return None
        if signal == "STOP":
            self.logger.info("JS endpoint scan %s stopped after JS id %s",
                             scan_run_id, last_js_id)
            self.mark_cancelled(scan_run_id)
            return "STOP"
        # PAUSE — persist a keyset checkpoint so resume continues from here.
        checkpoint = {
            "last_js_id": str(last_js_id) if last_js_id else None,
            "js_processed": metrics.js_processed,
            "js_failed": metrics.js_failed,
            "new_endpoints": metrics.new_endpoints,
            f"raw_{LINKFINDER}": tool_raw_counts.get(LINKFINDER, 0),
            f"raw_{XNLINKFINDER}": tool_raw_counts.get(XNLINKFINDER, 0),
            f"raw_{JSLUICE}": tool_raw_counts.get(JSLUICE, 0),
        }
        self.logger.info("JS endpoint scan %s paused after JS id %s",
                         scan_run_id, last_js_id)
        self.mark_paused(scan_run_id, resume_state=checkpoint)
        return "PAUSE"

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------

    def _process_batch(
        self,
        db,
        program_id: uuid.UUID,
        scope_id: uuid.UUID,
        host_map: dict[str, uuid.UUID],
        extractors: dict,
        available: dict[str, bool],
        batch: list[tuple[str, uuid.UUID | None, uuid.UUID | None]],
        now: datetime,
        metrics: EndpointMetrics,
        tool_raw_counts: dict[str, int],
        ep_raw: Path,
    ) -> None:
        """Download one batch of JS, extract with all tools, merge, persist.

        Downloaded JS + all scratch files are deleted before this returns, even
        on error (the download manager's context manager guarantees cleanup).
        """
        # (js_url, js_file_id) pairs for the download manager.
        js_items = [(url, jid) for url, jid, _ in batch]
        # js_url -> (js_file_id, host_id) for attribution after resolution.
        meta: dict[str, tuple[uuid.UUID | None, uuid.UUID | None]] = {
            url: (jid, hid) for url, jid, hid in batch
        }

        with JsDownloadManager() as dl:
            downloaded, failed = dl.download_batch(js_items)
            metrics.js_failed += len(failed)

            # One summary line per batch instead of one warning per dead URL.
            if failed:
                self.logger.info(
                    "JS batch: %d downloaded, %d failed (e.g. dead/404 URLs)",
                    len(downloaded), len(failed),
                )

            if not downloaded:
                return

            # Map local file path -> originating JS URL (base for resolution).
            path_to_url = {d.path: d.url for d in downloaded}
            js_paths = [d.path for d in downloaded]

            # Run all extractors in parallel over the batch's files.
            per_tool = self._run_extractors_parallel(
                extractors, available, js_paths, metrics, tool_raw_counts, ep_raw,
            )
            metrics.js_processed += len(downloaded)

            # Merge: normalized_url -> {"tools": set, "js_url": str, ...}
            merged = self._merge_and_resolve(per_tool, path_to_url)

        # temp JS is now deleted (context manager exited) — persist from memory.
        if merged:
            self._persist_endpoints(
                db, program_id, scope_id, host_map, merged, now, metrics,
            )

    def _run_extractors_parallel(
        self,
        extractors: dict,
        available: dict[str, bool],
        js_paths: list[Path],
        metrics: EndpointMetrics,
        tool_raw_counts: dict[str, int],
        ep_raw: Path,
    ) -> dict[str, list[tuple[str, Path]]]:
        """Run every available extractor concurrently over *js_paths*.

        Returns ``{tool_name: [(raw_hit, source_js_path), ...]}``. For
        directory/batch tools (XNLinkFinder) we cannot attribute a hit back to a
        single file, so those hits are paired with ``None`` and resolved against
        each downloaded JS base as a fallback is *not* done — instead
        per-file tools (LinkFinder, JSluice) carry precise provenance while
        XNLinkFinder hits are resolved using their own already-absolute form
        (it emits absolute URLs) or dropped if still relative.
        """
        results: dict[str, list[tuple[str, Path | None]]] = {}

        def _run(name: str):
            tool = extractors[name]
            t0 = time.monotonic()
            if name in (LINKFINDER, JSLUICE):
                hits = self._run_per_file_tool(name, tool, js_paths)
            else:
                hits = self._run_batch_tool(name, tool, js_paths)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            self.logger.info(
                "Tool=%s files=%d raw_endpoints=%d status=%s time=%dms",
                name, len(js_paths), len(hits), "SUCCESS", elapsed_ms,
            )
            return name, hits

        runnable = [n for n in extractors if available.get(n)]
        with ThreadPoolExecutor(max_workers=max(1, len(runnable))) as pool:
            futures = [pool.submit(_run, n) for n in runnable]
            for fut in futures:
                try:
                    name, hits = fut.result()
                    results[name] = hits
                    tool_raw_counts[name] += len(hits)
                except Exception as exc:  # one tool failing never kills the batch
                    self.logger.warning("Extractor raised during batch: %s", exc)

        # Per-tool raw metric roll-up.
        metrics.linkfinder_count += len(results.get(LINKFINDER, []))
        metrics.xnlinkfinder_count += len(results.get(XNLINKFINDER, []))
        metrics.jsluice_count += len(results.get(JSLUICE, []))
        return results

    def _run_per_file_tool(
        self, name: str, tool, js_paths: list[Path]
    ) -> list[tuple[str, Path | None]]:
        """Run a per-file extractor, retrying individual files on batch failure.

        Returns ``(raw_hit, source_js_path)`` pairs so each hit resolves against
        its own JS file. JSluice returns structured objects — we take ``.url``.
        """
        hits: list[tuple[str, Path | None]] = []
        try:
            if name == JSLUICE:
                for ep in tool.run(js_paths):
                    # JSluice reports the file each hit came from.
                    src = Path(ep.filename) if ep.filename else None
                    hits.append((ep.url, src))
            else:  # LinkFinder — run per file for precise provenance
                for p in js_paths:
                    for raw in tool.run([p]):
                        hits.append((raw, p))
            return hits
        except Exception as exc:
            self.logger.warning("%s batch failed (%s) — retrying per file", name, exc)

        # Per-file retry path — isolate the offending file(s).
        hits = []
        for p in js_paths:
            try:
                if name == JSLUICE:
                    for ep in tool.run_single(p):
                        hits.append((ep.url, p))
                else:
                    for raw in tool.run([p]):
                        hits.append((raw, p))
            except Exception as exc:
                self.logger.warning("%s failed on %s: %s", name, p.name, exc)
        return hits

    def _run_batch_tool(
        self, name: str, tool, js_paths: list[Path]
    ) -> list[tuple[str, Path | None]]:
        """Run a directory/batch extractor (XNLinkFinder). No per-file provenance."""
        try:
            return [(raw, None) for raw in tool.run(js_paths)]
        except Exception as exc:
            self.logger.warning("%s failed on batch: %s", name, exc)
            return []

    def _merge_and_resolve(
        self,
        per_tool: dict[str, list[tuple[str, Path | None]]],
        path_to_url: dict[Path, str],
    ) -> dict[str, dict]:
        """Resolve every raw hit to an absolute URL and merge by normalized_url.

        Returns ``{normalized_url: {absolute, scheme, host, path, query,
        fragment, tools: set, js_url: str}}``. A hit whose source file is known
        resolves against that JS file's URL; batch-tool hits (no source) must
        already be absolute or they are dropped.
        """
        merged: dict[str, dict] = {}
        # Any downloaded JS URL — used only as a last-resort base for batch-tool
        # hits that happen to be relative (rare; usually they're absolute).
        fallback_base = next(iter(path_to_url.values()), None)
        scope_target = getattr(self, "_scope_target", None)

        for tool_name, hits in per_tool.items():
            for raw, src_path in hits:
                base = path_to_url.get(src_path) if src_path else fallback_base
                if base is None:
                    continue
                resolved = resolve_endpoint(raw, base)
                if resolved is None:
                    continue
                # Scope gate: only keep endpoints whose host is in scope. A JS
                # file often references off-scope CDN/third-party hosts that
                # can't be reported — drop them so they're never stored.
                if scope_target and not is_host_in_scope(resolved.host, scope_target):
                    continue
                entry = merged.get(resolved.normalized_url)
                if entry is None:
                    merged[resolved.normalized_url] = {
                        "absolute": resolved.absolute_url,
                        "scheme": resolved.scheme,
                        "host": resolved.host,
                        "path": resolved.path,
                        "query": resolved.query,
                        "fragment": resolved.fragment,
                        "tools": {tool_name},
                        "js_url": base,
                    }
                else:
                    entry["tools"].add(tool_name)
        return merged

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_endpoints(
        self,
        db,
        program_id: uuid.UUID,
        scope_id: uuid.UUID,
        host_map: dict[str, uuid.UUID],
        merged: dict[str, dict],
        now: datetime,
        metrics: EndpointMetrics,
    ) -> None:
        items = list(merged.items())
        for start in range(0, len(items), DB_BATCH_SIZE):
            chunk = items[start:start + DB_BATCH_SIZE]
            rows: list[dict] = []
            norm_to_tools: dict[str, set[str]] = {}
            norm_to_js: dict[str, str] = {}
            for normalized, data in chunk:
                host = data["host"]
                host_id = host_map.get(host)
                js_url = data["js_url"]
                norm_to_tools[normalized] = data["tools"]
                norm_to_js[normalized] = js_url
                rows.append({
                    "id": uuid.uuid4(),
                    "program_id": program_id,
                    "scope_id": scope_id,
                    "host_id": host_id,
                    "js_file_id": None,  # resolved below via js_url when known
                    "absolute_url": data["absolute"],
                    "normalized_url": normalized,
                    "scheme": data["scheme"],
                    "host": host[:255] if host else None,
                    "path": data["path"] or None,
                    "query": data["query"] or None,
                    "fragment": data["fragment"] or None,
                    "discovery_tools": sorted(data["tools"]),
                    "discovery_source": DiscoverySource.JS_DISCOVERY.value,
                    "source_js_file": js_url,
                    "first_seen": now,
                    "last_seen": now,
                    "created_at": now,
                    "updated_at": now,
                })

            new_rows, existing_rows = self.endpoint_repo.bulk_upsert(db, rows)
            metrics.new_endpoints += len(new_rows)

            # Per-tool source attribution for every affected endpoint.
            id_by_norm = {r["normalized_url"]: r["id"] for r in (new_rows + existing_rows)}
            source_rows: list[dict] = []
            for normalized, tools in norm_to_tools.items():
                ep_id = id_by_norm.get(normalized)
                if not ep_id:
                    continue
                for tool in tools:
                    source_rows.append({"endpoint_id": ep_id, "tool_name": tool})
            self.endpoint_repo.bulk_insert_sources(db, source_rows)

            # Counters — only NEW endpoints contribute; roll up per host + subdomain.
            host_deltas: dict[uuid.UUID, int] = {}
            name_deltas: dict[str, int] = {}
            id_to_host = {r["id"]: r.get("host_id") for r in new_rows}
            for r in new_rows:
                hid = r.get("host_id")
                if hid:
                    host_deltas[hid] = host_deltas.get(hid, 0) + 1
            # Subdomain counter is keyed by host name; derive from the merged host.
            for normalized in norm_to_tools:
                ep_id = id_by_norm.get(normalized)
                if ep_id in id_to_host:  # only new rows are in id_to_host
                    host = merged[normalized]["host"]
                    if host:
                        name_deltas[host] = name_deltas.get(host, 0) + 1

            self.host_repo.bulk_increment_endpoint_counts(db, host_deltas)
            self.subdomain_repo.bulk_increment_endpoint_counts(db, scope_id, name_deltas)

    def _persist_run_artifacts(self, db, ep_proc: Path, scope_id: uuid.UUID) -> None:
        """Write the merged endpoint inventory artifact for the scope.

        Streams normalized URLs from the DB so memory stays flat even for
        millions of endpoints.
        """
        target = ep_proc / "merged_endpoints.txt"
        with target.open("w", encoding="utf-8") as fh:
            offset = 0
            page = 10_000
            while True:
                rows = self.endpoint_repo.list_by_scope(
                    db, scope_id, offset=offset, limit=page, sort_by="normalized_url",
                )
                if not rows:
                    break
                for ep in rows:
                    fh.write(ep.normalized_url + "\n")
                offset += len(rows)
                if len(rows) < page:
                    break

    # ------------------------------------------------------------------
    # Tool executions + metrics
    # ------------------------------------------------------------------

    def _record_tool_executions(
        self, db, scan_run_id: uuid.UUID, tool_raw_counts: dict[str, int],
        metrics: EndpointMetrics,
    ) -> None:
        for name, raw in tool_raw_counts.items():
            rec = self.tool_execution_repo.create(
                db,
                scan_run_id=scan_run_id,
                tool_name=name.lower(),
                command=f"{name.lower()} <js files>",
                status=ToolExecutionStatus.RUNNING.value,
                started_at=datetime.now(timezone.utc),
            )
            status = (
                ToolExecutionStatus.FAILED if name in metrics.tool_errors
                else ToolExecutionStatus.COMPLETED
            )
            self.tool_execution_repo.update(
                db, rec,
                status=status.value,
                error_message=metrics.tool_errors.get(name),
                raw_records_found=raw,
                records_found=raw,
                finished_at=datetime.now(timezone.utc),
            )

    def _update_scan_metrics(
        self, db, scan_run_id: uuid.UUID, metrics: EndpointMetrics,
        tool_raw_counts: dict[str, int],
    ) -> None:
        db.execute(
            update(ScanRun)
            .where(ScanRun.id == scan_run_id)
            .values(
                linkfinder_count=tool_raw_counts.get(LINKFINDER, 0),
                xnlinkfinder_count=tool_raw_counts.get(XNLINKFINDER, 0),
                jsluice_count=tool_raw_counts.get(JSLUICE, 0),
                js_processed_count=metrics.js_processed,
                js_failed_count=metrics.js_failed,
                total_endpoints_count=metrics.total_endpoints,
                new_endpoints_count=metrics.new_endpoints,
            )
        )
        db.commit()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_extractors(self, scope_target: str) -> dict:
        """Instantiate every endpoint extractor. Register new tools here only."""
        return {
            LINKFINDER: LinkFinderRunner(timeout=120),
            XNLINKFINDER: XnLinkFinderRunner(timeout=300, scope_filter=scope_target or "*"),
            JSLUICE: JsluiceRunner(timeout=300, concurrency=4),
        }

    def _load_scan_data(self, db, scan_run_id: uuid.UUID):
        from backend.services.scan_run_service import ScanRunService
        svc = ScanRunService()
        scan_run = svc.get_scan_run(db=db, scan_run_id=scan_run_id)
        program = self.program_service.get_program(db=db, program_id=scan_run.program_id)
        scope = self.scope_service.get_scope(db=db, scope_id=scan_run.scope_id)
        return scan_run, program, scope


# ------------------------------------------------------------------
# Celery task
# ------------------------------------------------------------------

@celery_app.task(name="workers.js_endpoint_worker.run_js_endpoint_scan", bind=True)
def run_js_endpoint_scan(self, scan_run_id: str) -> None:
    JsEndpointWorker().run_scan(scan_run_id)
