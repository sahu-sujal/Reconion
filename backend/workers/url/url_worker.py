"""Content Discovery worker — Phase 5.

Pipeline per scan (scan_type = CONTENT_DISCOVERY):

    1.  Load live hosts (HTTP) + bare hostnames for the scope from DB
    2.  Run historical tools (gau, waybackurls) and crawlers (katana, hakrawler)
        in parallel, streaming raw output to disk
    3.  Merge → normalize → deduplicate across all tools, tracking per-URL sources
    4.  Bulk-upsert URL rows + JsFile rows (ON CONFLICT scope_id key)
    5.  Bulk-insert per-tool source attribution rows
    6.  Maintain hosts.url_count / hosts.js_count counters (new rows only)
    7.  Persist raw + merged artifacts to storage
    8.  Update ScanRun metrics
    9.  Send Discord notification

Tool failures are isolated — one tool erroring does not abort the others, and
the scan still records whatever the surviving tools discovered.
"""

from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

from backend.celery_app import celery_app
from backend.queues.redis_client import release_scope_lock
from backend.services.program_service import ProgramService
from backend.services.scope_service import ScopeService
from backend.services.storage_service import StorageService
from database.models.enums import ToolExecutionStatus
from database.models.host import Host
from database.models.http_response import HttpResponse
from database.models.scan_run import ScanRun
from repositories.host_repository import HostRepository
from repositories.js_file_repository import JsFileRepository
from repositories.tool_execution_repository import ToolExecutionRepository
from repositories.url_repository import URLRepository
from tools.common.scope_filter import is_host_in_scope
from tools.common.url_utils import is_js_url, parse_url
from tools.url.gau_runner import GauRunner
from tools.url.hakrawler_runner import HakrawlerRunner
from tools.url.katana_runner import KatanaRunner
from tools.url.waybackurls_runner import WaybackurlsRunner
from tools.javascript.subjs import SubjsRunner
from workers.base.base_worker import BaseWorker

DB_BATCH_SIZE = 10_000

# Tool source labels (match UrlSource enum values)
SRC_GAU = "GAU"
SRC_WAYBACKURLS = "WAYBACKURLS"
SRC_KATANA = "KATANA"
SRC_HAKRAWLER = "HAKRAWLER"
SRC_SUBJS = "SUBJS"

# Temporarily disabled — waybackurls consistently times out at 1800s and
# contributes 0 URLs. Flip back to True (or set ENABLE_WAYBACKURLS=1 in the
# environment) to re-enable it once its performance is acceptable.
ENABLE_WAYBACKURLS = os.getenv("ENABLE_WAYBACKURLS", "0") == "1"


@dataclass
class ContentDiscoveryMetrics:
    gau_count: int = 0
    waybackurls_count: int = 0
    katana_count: int = 0
    hakrawler_count: int = 0
    subjs_count: int = 0
    merged_raw: int = 0
    total_urls: int = 0      # unique normalized URLs upserted this run
    new_urls: int = 0
    total_js: int = 0
    new_js: int = 0
    tool_errors: dict = field(default_factory=dict)


class UrlScanWorker(BaseWorker):
    def __init__(self) -> None:
        super().__init__(name="url_worker")
        self.program_service = ProgramService()
        self.scope_service = ScopeService()
        self.storage_service = StorageService()
        self.host_repo = HostRepository()
        self.url_repo = URLRepository()
        self.js_repo = JsFileRepository()
        self.tool_execution_repo = ToolExecutionRepository()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run_scan(self, scan_run_id: str) -> None:
        db = self.get_db()
        scan_run = None
        metrics = ContentDiscoveryMetrics()
        started = datetime.now(timezone.utc)

        try:
            scan_run_uuid = uuid.UUID(scan_run_id)
            scan_run, program, scope = self._load_scan_data(db, scan_run_uuid)

            # Resume path: paused before chaining → just chain JS endpoint discovery.
            resume = scan_run.resume_state or {}
            if resume.get("pending_chain") == "JS_ENDPOINT":
                self.mark_completed(scan_run_id, records_found=scan_run.records_found or 0)
                self.scan_run_service.update_scan_run(
                    db=db, scan_run_id=scan_run_id, clear_resume_state=True,
                )
                self._chain_js_endpoint_scan(db, program.id, scope.id)
                return

            self.mark_running(scan_run_id)

            # Scope target used to reject out-of-scope URLs/JS at merge time —
            # in bug bounty, out-of-scope assets can't be reported, so they are
            # never stored.
            self._scope_target = scope.target

            self.storage_service.init_scope_directories_by_id(program.id, scope.id)
            urls_raw = self.storage_service.get_raw_path_by_id(program.id, scope.id, "urls")
            urls_proc = self.storage_service.get_processed_path_by_id(program.id, scope.id, "urls")
            js_raw = self.storage_service.get_raw_path_by_id(program.id, scope.id, "js")

            now = datetime.now(timezone.utc)

            # ---- Step 1: Load live hosts -------------------------------- #
            live_urls, hostnames = self._load_inputs(db, scope.id)
            self.logger.info(
                "Content discovery: %d live host URLs, %d hostnames",
                len(live_urls), len(hostnames),
            )
            if not live_urls and not hostnames:
                self._update_scan_metrics(db, scan_run.id, metrics)
                self.mark_completed(scan_run_id, records_found=0)
                return

            # ---- Step 2: Run tools in parallel -------------------------- #
            # value (normalized url) -> set of source labels
            url_sources: dict[str, set[str]] = {}
            js_sources: dict[str, set[str]] = {}

            self._run_tools(
                db, scan_run.id, hostnames, live_urls,
                url_sources, js_sources, metrics,
                urls_raw, js_raw,
            )

            metrics.total_urls = len(url_sources)
            metrics.total_js = len(js_sources)

            # ---- Step 7: Persist merged artifacts ----------------------- #
            self.storage_service.save_lines_artifact(
                urls_proc, "merged_urls.txt", sorted(url_sources),
            )
            (urls_raw / "merged_urls.json").write_text(
                "\n".join(
                    json.dumps({"url": u, "sources": sorted(s)})
                    for u, s in url_sources.items()
                ),
                encoding="utf-8",
            )
            (js_raw / "merged_js.json").write_text(
                "\n".join(
                    json.dumps({"url": u, "sources": sorted(s)})
                    for u, s in js_sources.items()
                ),
                encoding="utf-8",
            )

            # ---- Steps 4-6: Persist to DB ------------------------------- #
            host_map = self.host_repo.map_hostnames_to_ids(db, scope.id)
            self._persist_urls(db, program.id, scope.id, host_map, url_sources, now, metrics)
            self._persist_js(db, program.id, scope.id, host_map, js_sources, now, metrics)

            # ---- Step 8: Metrics ---------------------------------------- #
            self._update_scan_metrics(db, scan_run.id, metrics)
            self.mark_completed(scan_run_id, records_found=metrics.total_urls)

            # ---- Chain: JS endpoint discovery (Phase 6.1) --------------- #
            # Only chain when we actually discovered JS files to process.
            if metrics.total_js > 0:
                signal = self.check_control(scan_run_id)
                if signal == "STOP":
                    self.logger.info("Scan %s stopped before chaining JS endpoints", scan_run_id)
                    self.mark_cancelled(scan_run_id)
                    return
                if signal == "PAUSE":
                    self.logger.info("Scan %s paused before chaining JS endpoints", scan_run_id)
                    self.mark_paused(scan_run_id, resume_state={"pending_chain": "JS_ENDPOINT"})
                    return
                try:
                    self._chain_js_endpoint_scan(db, program.id, scope.id)
                except Exception as chain_exc:
                    self.logger.warning(
                        "Failed to chain JS endpoint scan after content discovery %s: %s",
                        scan_run_id, chain_exc,
                    )

            self.logger.info(
                "Content discovery %s done — urls=%d (new=%d) js=%d (new=%d)",
                scan_run_id, metrics.total_urls, metrics.new_urls,
                metrics.total_js, metrics.new_js,
            )

            # ---- Step 9: Discord ---------------------------------------- #
            from workers.notification.discord_worker import send_content_discovery_notification
            duration = (datetime.now(timezone.utc) - started).total_seconds()
            send_content_discovery_notification(
                webhook_url=None,
                program_name=program.name,
                scope_target=scope.target,
                metrics=metrics,
                duration_seconds=duration,
            )

        except Exception as exc:
            self.logger.exception("Content discovery scan %s failed: %s", scan_run_id, exc)
            self.mark_failed(scan_run_id, str(exc))
        finally:
            if scan_run is not None:
                try:
                    release_scope_lock(scan_run.scope_id)
                except Exception:
                    pass
            db.close()

    # ------------------------------------------------------------------
    # Tool execution (parallel)
    # ------------------------------------------------------------------

    def _run_tools(
        self,
        db,
        scan_run_id: uuid.UUID,
        hostnames: list[str],
        live_urls: list[str],
        url_sources: dict[str, set[str]],
        js_sources: dict[str, set[str]],
        metrics: ContentDiscoveryMetrics,
        urls_raw: Path,
        js_raw: Path,
    ) -> None:
        """Run all four tools in parallel; merge results as each completes."""

        # Each task returns (label, raw_count, set_of_raw_url_strings) and writes
        # its raw output artifact to the scope's storage tree (per spec layout).
        def _gau() -> tuple[str, int, set[str]]:
            out = urls_raw / "gau.json"
            raw = GauRunner(timeout=1800).run_to_file(hostnames, out)
            return SRC_GAU, raw, _read_lines(out)

        def _wayback() -> tuple[str, int, set[str]]:
            out = urls_raw / "waybackurls.json"
            raw = WaybackurlsRunner(timeout=1800).run_to_file(hostnames, out)
            return SRC_WAYBACKURLS, raw, _read_lines(out)

        def _katana() -> tuple[str, int, set[str]]:
            out = urls_raw / "katana.json"
            raw = KatanaRunner(timeout=1800).crawl_to_file(live_urls, out)
            eps = KatanaRunner._iter_endpoints(out)
            # JS endpoints discovered by katana are also written separately
            (js_raw / "katana_js.json").write_text(
                "\n".join(sorted(e for e in eps if is_js_url(e))),
                encoding="utf-8",
            )
            return SRC_KATANA, raw, eps

        def _hakrawler() -> tuple[str, int, set[str]]:
            out = urls_raw / "hakrawler.json"
            raw = HakrawlerRunner(timeout=1800).crawl_to_file(live_urls, out)
            urls = _read_lines(out)
            (js_raw / "hakrawler_js.json").write_text(
                "\n".join(sorted(u for u in urls if is_js_url(u))),
                encoding="utf-8",
            )
            return SRC_HAKRAWLER, raw, urls

        def _subjs() -> tuple[str, int, set[str]]:
            # subjs is JS-only: it fetches live hosts and returns JS file URLs.
            # Raw output is streamed to the scope's js/ artifact tree.
            out = js_raw / "subjs.json"
            raw = SubjsRunner(timeout=1800, concurrency=20).run_to_file(live_urls, out)
            js_urls = _read_lines(out)
            self.logger.info(
                "Tool=SUBJS hosts=%d js_found=%d status=SUCCESS",
                len(live_urls), len(js_urls),
            )
            return SRC_SUBJS, raw, js_urls

        tasks = {}
        if hostnames:
            tasks[SRC_GAU] = _gau
            if ENABLE_WAYBACKURLS:
                tasks[SRC_WAYBACKURLS] = _wayback
        if live_urls:
            tasks[SRC_KATANA] = _katana
            tasks[SRC_HAKRAWLER] = _hakrawler
            tasks[SRC_SUBJS] = _subjs

        exec_recs = {
            label: self._create_tool_execution(db, scan_run_id, label.lower(), f"{label.lower()} <hosts>")
            for label in tasks
        }

        results: dict[str, tuple[int, set[str]]] = {}
        with ThreadPoolExecutor(max_workers=5) as pool:
            future_map = {pool.submit(fn): label for label, fn in tasks.items()}
            for future in as_completed(future_map):
                label = future_map[future]
                try:
                    lbl, raw_count, urls = future.result()
                    results[lbl] = (raw_count, urls)
                    self._finalize_tool_execution(
                        db, exec_recs[lbl], ToolExecutionStatus.COMPLETED,
                        raw_records_found=raw_count, records_found=len(urls),
                    )
                except Exception as exc:  # one tool failing must not kill the scan
                    metrics.tool_errors[label] = str(exc)
                    self.logger.warning("Tool %s failed during content discovery: %s", label, exc)
                    self._finalize_tool_execution(
                        db, exec_recs[label], ToolExecutionStatus.FAILED, error_message=str(exc),
                    )

        # Record per-tool counts + merge into source maps
        for label, (raw_count, urls) in results.items():
            if label == SRC_GAU:
                metrics.gau_count = raw_count
            elif label == SRC_WAYBACKURLS:
                metrics.waybackurls_count = raw_count
            elif label == SRC_KATANA:
                metrics.katana_count = raw_count
            elif label == SRC_HAKRAWLER:
                metrics.hakrawler_count = raw_count
            elif label == SRC_SUBJS:
                metrics.subjs_count = raw_count
            metrics.merged_raw += len(urls)
            # subjs output is always JS files — force JS classification so URLs
            # like "…/script?v=2" are still recorded as JS.
            self._merge(urls, label, url_sources, js_sources, force_js=(label == SRC_SUBJS))

    def _merge(
        self,
        raw_urls: set[str],
        label: str,
        url_sources: dict[str, set[str]],
        js_sources: dict[str, set[str]],
        force_js: bool = False,
    ) -> None:
        """Normalize + deduplicate one tool's URLs into the shared source maps.

        Out-of-scope URLs/JS (any host not under the scope root domain) are
        dropped here so they never reach the DB. ``force_js`` marks every input
        as a JS file — used for JS-only discovery tools (subjs) whose output may
        not always end in ``.js`` (e.g. ``/script?v=2``).
        """
        scope_target = getattr(self, "_scope_target", None)
        for raw in raw_urls:
            parsed = parse_url(raw)
            if parsed is None:
                continue
            # Scope gate: skip anything whose host isn't in scope.
            if scope_target and not is_host_in_scope(parsed.host, scope_target):
                continue
            if force_js or is_js_url(raw):
                js_sources.setdefault(parsed.normalized, set()).add(label)
                # A JS file is also a URL — record it in both tables.
                url_sources.setdefault(parsed.normalized, set()).add(label)
            else:
                url_sources.setdefault(parsed.normalized, set()).add(label)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_urls(
        self,
        db,
        program_id: uuid.UUID,
        scope_id: uuid.UUID,
        host_map: dict[str, uuid.UUID],
        url_sources: dict[str, set[str]],
        now: datetime,
        metrics: ContentDiscoveryMetrics,
    ) -> None:
        items = list(url_sources.items())
        url_deltas: dict[uuid.UUID, int] = {}

        for start in range(0, len(items), DB_BATCH_SIZE):
            batch = items[start:start + DB_BATCH_SIZE]
            rows: list[dict[str, Any]] = []
            normalized_to_sources: dict[str, set[str]] = {}
            for normalized, sources in batch:
                parsed = parse_url(normalized)
                if parsed is None:
                    continue
                normalized_to_sources[normalized] = sources
                host_id = host_map.get(parsed.host)
                rows.append({
                    "id": uuid.uuid4(),
                    "program_id": program_id,
                    "scope_id": scope_id,
                    "host_id": host_id,
                    "url": parsed.raw,
                    "normalized_url": parsed.normalized,
                    "scheme": parsed.scheme,
                    "host": parsed.host[:255],
                    "path": parsed.path,
                    "query": parsed.query or None,
                    "fragment": parsed.fragment or None,
                    "extension": parsed.extension,
                    "directory": parsed.directory,
                    "filename": parsed.filename[:512] if parsed.filename else None,
                    "depth": parsed.depth,
                    "parameter_count": parsed.parameter_count,
                    "has_parameters": parsed.has_parameters,
                    "status": None,
                    "source": ",".join(sorted(sources))[:255],
                    "first_seen": now,
                    "last_seen": now,
                    "created_at": now,
                    "updated_at": now,
                })

            new_rows, existing_rows = self.url_repo.bulk_upsert(db, rows)
            metrics.new_urls += len(new_rows)

            # Source attribution for every affected row
            id_by_norm = {r["normalized_url"]: r["id"] for r in (new_rows + existing_rows)}
            source_rows: list[dict[str, Any]] = []
            for normalized, sources in normalized_to_sources.items():
                url_id = id_by_norm.get(normalized)
                if not url_id:
                    continue
                for src in sources:
                    source_rows.append({"url_id": url_id, "tool_name": src})
            self.url_repo.bulk_insert_sources(db, source_rows)

            # Counters: only newly inserted URLs increment host.url_count
            for r in new_rows:
                hid = r.get("host_id")
                if hid:
                    url_deltas[hid] = url_deltas.get(hid, 0) + 1

        self.host_repo.bulk_increment_counts(db, url_deltas, {})

    def _persist_js(
        self,
        db,
        program_id: uuid.UUID,
        scope_id: uuid.UUID,
        host_map: dict[str, uuid.UUID],
        js_sources: dict[str, set[str]],
        now: datetime,
        metrics: ContentDiscoveryMetrics,
    ) -> None:
        items = list(js_sources.items())
        js_deltas: dict[uuid.UUID, int] = {}

        for start in range(0, len(items), DB_BATCH_SIZE):
            batch = items[start:start + DB_BATCH_SIZE]
            rows: list[dict[str, Any]] = []
            url_to_sources: dict[str, set[str]] = {}
            for normalized, sources in batch:
                parsed = parse_url(normalized)
                if parsed is None:
                    continue
                url_to_sources[parsed.normalized] = sources
                host_id = host_map.get(parsed.host)
                rows.append({
                    "id": uuid.uuid4(),
                    "program_id": program_id,
                    "scope_id": scope_id,
                    "host_id": host_id,
                    "url": parsed.normalized,
                    "filename": parsed.filename[:512] if parsed.filename else None,
                    "directory": parsed.directory,
                    "extension": parsed.extension,
                    "source": ",".join(sorted(sources))[:255],
                    "first_seen": now,
                    "last_seen": now,
                    "created_at": now,
                    "updated_at": now,
                })

            new_rows, existing_rows = self.js_repo.bulk_upsert(db, rows)
            metrics.new_js += len(new_rows)

            id_by_url = {r["url"]: r["id"] for r in (new_rows + existing_rows)}
            source_rows: list[dict[str, Any]] = []
            for url_str, sources in url_to_sources.items():
                js_id = id_by_url.get(url_str)
                if not js_id:
                    continue
                for src in sources:
                    source_rows.append({"js_file_id": js_id, "tool_name": src})
            self.js_repo.bulk_insert_sources(db, source_rows)

            for r in new_rows:
                hid = r.get("host_id")
                if hid:
                    js_deltas[hid] = js_deltas.get(hid, 0) + 1

        self.host_repo.bulk_increment_counts(db, {}, js_deltas)

    # ------------------------------------------------------------------
    # Inputs
    # ------------------------------------------------------------------

    def _load_inputs(self, db, scope_id: uuid.UUID) -> tuple[list[str], list[str]]:
        """Return (live_host_urls, bare_hostnames) for the scope.

        Live URLs (with scheme) seed the crawlers; bare hostnames seed the
        historical tools. We read live hosts from the hosts table (status_code
        set) and prefer their scheme; fall back to http_responses URLs.
        """
        live_urls: list[str] = []
        hostnames: list[str] = []

        host_rows = db.execute(
            select(Host.host, Host.scheme, Host.port, Host.status_code)
            .where(Host.scope_id == scope_id)
        ).fetchall()
        for r in host_rows:
            hostnames.append(r.host)
            if r.status_code is not None:
                scheme = r.scheme or "https"
                if r.port and r.port not in (80, 443):
                    live_urls.append(f"{scheme}://{r.host}:{r.port}")
                else:
                    live_urls.append(f"{scheme}://{r.host}")

        # Supplement crawler seeds with any distinct http_response URLs.
        if not live_urls:
            resp_rows = db.execute(
                select(HttpResponse.url).where(HttpResponse.scope_id == scope_id)
            ).fetchall()
            live_urls = [r.url for r in resp_rows]

        return sorted(set(live_urls)), sorted(set(hostnames))

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

    def _chain_js_endpoint_scan(self, db, program_id: uuid.UUID, scope_id: uuid.UUID) -> None:
        """Create a JS_ENDPOINT ScanRun and enqueue run_js_endpoint_scan (Phase 6.1)."""
        from backend.services.scan_run_service import ScanRunService
        from database.models.enums import ScanStatus, ScanType

        svc = ScanRunService()
        ep_scan = svc.create_scan_run(
            db=db,
            program_id=program_id,
            scope_id=scope_id,
            scan_type=ScanType.JS_ENDPOINT.value,
            worker_name="js_endpoint_worker",
            status=ScanStatus.PENDING.value,
        )
        celery_app.send_task(
            "workers.js_endpoint_worker.run_js_endpoint_scan",
            args=[str(ep_scan.id)],
            countdown=2,
        )
        self.logger.info("Chained JS endpoint scan %s for scope %s", ep_scan.id, scope_id)

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

    def _update_scan_metrics(self, db, scan_run_id: uuid.UUID, metrics: ContentDiscoveryMetrics) -> None:
        db.execute(
            update(ScanRun)
            .where(ScanRun.id == scan_run_id)
            .values(
                gau_count=metrics.gau_count,
                waybackurls_count=metrics.waybackurls_count,
                katana_count=metrics.katana_count,
                hakrawler_count=metrics.hakrawler_count,
                subjs_count=metrics.subjs_count,
                total_urls_count=metrics.total_urls,
                new_urls_count=metrics.new_urls,
                total_js_count=metrics.total_js,
                new_js_count=metrics.new_js,
            )
        )
        db.commit()


def _read_lines(path: Path) -> set[str]:
    """Read non-empty stripped lines from a file into a set."""
    values: set[str] = set()
    if not path.exists():
        return values
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            v = line.strip()
            if v:
                values.add(v)
    return values


# ------------------------------------------------------------------
# Celery task
# ------------------------------------------------------------------

@celery_app.task(name="workers.url.url_worker.run_url_scan", bind=True)
def run_url_scan(self, scan_run_id: str) -> None:
    UrlScanWorker().run_scan(scan_run_id)
