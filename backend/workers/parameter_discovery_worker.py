"""Active Parameter Discovery worker — Phase 6.4.

ONE responsibility: discover hidden HTTP parameters on the **dynamic** assets
already stored in this scope's inventory, and build a centralized, deduplicated
Parameter Inventory linked back to each originating URL / Endpoint.

Routing is delegated to the Asset Classification Engine (Phase 6.3): the worker
streams only ``is_dynamic``/``is_api`` assets (APIs, dynamic pages, auth, admin,
upload, download, unknown-dynamic) and NEVER static resources (CSS, JS, images,
fonts, video, audio, archives, documents, source maps).

Pipeline (scan_type = PARAMETER_DISCOVERY)::

    stream dynamic assets (batched, keyset — constant memory)
        └─ per batch:
             ├─ Arjun (active probing) ┐  run in parallel, isolated failure
             └─ ParamSpider (archived) ┘
             normalize → classify type → merge (union tools) → dedupe
             bulk-upsert parameters (ON CONFLICT scope,asset,name → union tools)
             attribute per-tool sources
             maintain per-asset + per-host + per-subdomain parameter counters
             write raw tool artifacts
    persist merged artifact → update ScanRun metrics → Discord

Design notes:
  * Tools implement a common interface (``ParameterToolBase``); adding ParamMiner
    / a custom dictionary / an AI module is a one-line change to ``_build_tools``
    — the worker body and DB schema never change.
  * Tool failures are isolated: if Arjun fails, ParamSpider still runs, and vice
    versa. One tool failing never aborts the batch or the scan.
  * Never loads every asset into memory — assets are streamed by keyset page and
    parameters are bulk-upserted per batch.
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
from repositories.dynamic_asset_repository import DynamicAssetRepository
from repositories.host_repository import HostRepository
from repositories.parameter_repository import ParameterRepository
from repositories.subdomain_repository import SubdomainRepository
from repositories.tool_execution_repository import ToolExecutionRepository
from tools.common.parameter_utils import classify_parameter, normalize_parameter
from tools.common.scope_filter import host_of_url, is_host_in_scope
from tools.parameters.arjun import ArjunRunner
from tools.parameters.paramspider import ParamSpiderRunner
from workers.base.base_worker import BaseWorker

# How many dynamic assets to hand each tool per batch (bounds memory + tool time).
ASSET_BATCH_SIZE = int(os.getenv("PARAM_ASSET_BATCH_SIZE", "200"))
DB_BATCH_SIZE = 5_000

ARJUN = "ARJUN"
PARAMSPIDER = "PARAMSPIDER"


@dataclass
class ParameterMetrics:
    assets_total: int = 0        # dynamic assets in scope routed to discovery
    assets_scanned: int = 0      # assets handed to the tools
    arjun_count: int = 0         # raw parameter hits per tool (pre-merge)
    paramspider_count: int = 0
    total_parameters: int = 0    # unique parameters in scope after this run
    new_parameters: int = 0
    tool_errors: dict = field(default_factory=dict)


class ParameterDiscoveryWorker(BaseWorker):
    def __init__(self) -> None:
        super().__init__(name="parameter_discovery_worker")
        self.program_service = ProgramService()
        self.scope_service = ScopeService()
        self.storage_service = StorageService()
        self.param_repo = ParameterRepository()
        self.dynamic_repo = DynamicAssetRepository()
        self.host_repo = HostRepository()
        self.subdomain_repo = SubdomainRepository()
        self.tool_execution_repo = ToolExecutionRepository()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run_scan(self, scan_run_id: str) -> None:
        db = self.get_db()
        scan_run = None
        metrics = ParameterMetrics()
        started = datetime.now(timezone.utc)
        tool_raw_counts = {ARJUN: 0, PARAMSPIDER: 0}

        try:
            scan_run_uuid = uuid.UUID(scan_run_id)
            scan_run, program, scope = self._load_scan_data(db, scan_run_uuid)
            self.mark_running(scan_run_id)
            self._scope_target = scope.target

            self.storage_service.init_scope_directories_by_id(program.id, scope.id)
            param_proc = self.storage_service.get_processed_path_by_id(
                program.id, scope.id, "parameters")
            param_raw = self.storage_service.get_raw_path_by_id(
                program.id, scope.id, "parameters")

            metrics.assets_total = self.dynamic_repo.count_dynamic(db, scope.id)
            self.logger.info("Parameter discovery: %d dynamic assets in scope %s",
                             metrics.assets_total, scope.id)
            if metrics.assets_total == 0:
                self._update_scan_metrics(db, scan_run.id, metrics, tool_raw_counts)
                self.mark_completed(scan_run_id, records_found=0)
                return

            host_map = self.host_repo.map_hostnames_to_ids(db, scope.id)
            tools = self._build_tools()
            available = {name: t.health_check() for name, t in tools.items()}
            for name, ok in available.items():
                if not ok:
                    self.logger.warning("Parameter tool %s unavailable — skipping it", name)
            if not any(available.values()):
                # Neither tool is installed — record and finish cleanly.
                self.logger.warning("No parameter discovery tools available — nothing to do")
                self._update_scan_metrics(db, scan_run.id, metrics, tool_raw_counts)
                self.mark_completed(scan_run_id, records_found=0)
                return

            now = datetime.now(timezone.utc)

            batch: list = []
            for asset in self.dynamic_repo.iter_dynamic(
                db, scope.id, batch_size=ASSET_BATCH_SIZE
            ):
                batch.append(asset)
                if len(batch) >= ASSET_BATCH_SIZE:
                    self._process_batch(db, program, scope, host_map, tools, available,
                                        batch, now, metrics, tool_raw_counts, param_raw)
                    batch = []
                    if self._handle_batch_control(scan_run_id):
                        return
            if batch:
                self._process_batch(db, program, scope, host_map, tools, available,
                                    batch, now, metrics, tool_raw_counts, param_raw)

            metrics.total_parameters = self.param_repo.count_for_scope(db, scope.id)
            self._persist_run_artifact(db, param_proc, scope.id)
            self._record_tool_executions(db, scan_run.id, tool_raw_counts, metrics)
            self._update_scan_metrics(db, scan_run.id, metrics, tool_raw_counts)
            self.mark_completed(scan_run_id, records_found=metrics.new_parameters)

            self.logger.info(
                "Parameter discovery %s done — assets=%d scanned=%d params total=%d new=%d",
                scan_run_id, metrics.assets_total, metrics.assets_scanned,
                metrics.total_parameters, metrics.new_parameters,
            )

            from workers.notification.discord_worker import send_parameter_discovery_notification
            duration = (datetime.now(timezone.utc) - started).total_seconds()
            send_parameter_discovery_notification(
                webhook_url=None, program_name=program.name, scope_target=scope.target,
                metrics=metrics, duration_seconds=duration,
            )

        except Exception as exc:
            self.logger.exception("Parameter discovery scan %s failed: %s", scan_run_id, exc)
            self.mark_failed(scan_run_id, str(exc))
        finally:
            if scan_run is not None:
                try:
                    release_scope_lock(scan_run.scope_id)
                except Exception:
                    pass
            db.close()

    def _handle_batch_control(self, scan_run_id: str) -> bool:
        """React to a pause/stop signal between batches. Returns True to stop."""
        signal = self.check_control(scan_run_id)
        if signal == "STOP":
            self.logger.info("Parameter discovery scan %s stopped", scan_run_id)
            self.mark_cancelled(scan_run_id)
            return True
        if signal == "PAUSE":
            # Parameter discovery is idempotent (upsert), so pause simply stops;
            # a resume re-runs and re-converges without duplicates.
            self.logger.info("Parameter discovery scan %s paused", scan_run_id)
            self.mark_paused(scan_run_id, resume_state=None)
            return True
        return False

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------

    def _process_batch(self, db, program, scope, host_map, tools, available,
                       batch, now, metrics, tool_raw_counts, param_raw) -> None:
        # url -> asset (for attribution after tools resolve by URL). Keep the
        # first asset per URL; identical URLs across url/endpoint tables are rare
        # and attribution stays deterministic. A second index keyed on the URL
        # with its query stripped lets us re-attribute tool output (ParamSpider)
        # that reports the same path with a different query string.
        url_to_asset = {}
        base_to_asset = {}
        for a in batch:
            url_to_asset.setdefault(a.url, a)
            base_to_asset.setdefault(a.url.split("?", 1)[0], a)
        targets = list(url_to_asset.keys())
        metrics.assets_scanned += len(batch)

        per_tool = self._run_tools(tools, available, targets, metrics,
                                   tool_raw_counts, param_raw)
        merged = self._merge(per_tool, url_to_asset, base_to_asset, scope.target)
        if merged:
            self._persist_parameters(db, program, scope, host_map, url_to_asset,
                                     merged, now, metrics)

    def _run_tools(self, tools, available, targets, metrics, tool_raw_counts,
                   param_raw) -> dict[str, list]:
        """Run every available tool in parallel. Returns {tool: [RawParameter]}."""
        results: dict[str, list] = {}

        def _run(name: str):
            t0 = time.monotonic()
            found = tools[name].run(targets)
            self.logger.info("Tool=%s targets=%d raw_params=%d status=SUCCESS time=%dms",
                             name, len(targets), len(found),
                             int((time.monotonic() - t0) * 1000))
            return name, found

        runnable = [n for n in tools if available.get(n)]
        with ThreadPoolExecutor(max_workers=max(1, len(runnable))) as pool:
            futures = {pool.submit(_run, n): n for n in runnable}
            for fut in futures:
                name = futures[fut]
                try:
                    _name, found = fut.result()
                    results[name] = found
                    tool_raw_counts[name] += len(found)
                except Exception as exc:  # one tool failing never kills the batch
                    metrics.tool_errors[name] = str(exc)
                    self.logger.warning("Parameter tool %s raised during batch: %s", name, exc)

        metrics.arjun_count += len(results.get(ARJUN, []))
        metrics.paramspider_count += len(results.get(PARAMSPIDER, []))

        # Persist raw per-tool artifacts (append-friendly JSON lines).
        self._append_raw_artifacts(param_raw, results)
        return results

    def _merge(self, per_tool: dict[str, list], url_to_asset, base_to_asset,
               scope_target) -> dict[tuple, dict]:
        """Normalize, classify, and merge parameters across tools.

        Keyed by ``(asset_id, normalized_name)``. Out-of-scope hits (by asset
        host) and junk names are dropped. A parameter reported by both tools for
        the same asset unions their labels.
        """
        merged: dict[tuple, dict] = {}
        for tool_name, findings in per_tool.items():
            for rp in findings:
                normalized = normalize_parameter(rp.name)
                if not normalized:
                    continue
                asset = self._resolve_asset(rp.asset_url, url_to_asset, base_to_asset)
                if asset is None:
                    continue
                # Scope gate on the asset host.
                host = asset.host or host_of_url(asset.url)
                if scope_target and host and not is_host_in_scope(host, scope_target):
                    continue
                key = (asset.asset_id, normalized)
                entry = merged.get(key)
                if entry is None:
                    merged[key] = {
                        "asset": asset,
                        "parameter_name": normalized,
                        "parameter_type": classify_parameter(normalized),
                        "tools": {tool_name},
                    }
                else:
                    entry["tools"].add(tool_name)
        return merged

    @staticmethod
    def _resolve_asset(asset_url, url_to_asset, base_to_asset):
        """Map a tool-reported URL back to the originating asset.

        Arjun echoes the exact target URL we fed it, so an exact match resolves
        it. ParamSpider reports the archived URL with a (possibly different)
        query string, so we fall back to matching on the URL with its query
        stripped — attributing the parameter to the asset with the same path.
        """
        if not asset_url:
            return None
        asset = url_to_asset.get(asset_url)
        if asset is not None:
            return asset
        base = asset_url.split("?", 1)[0]
        return url_to_asset.get(base) or base_to_asset.get(base)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_parameters(self, db, program, scope, host_map, url_to_asset,
                            merged, now, metrics) -> None:
        items = list(merged.items())
        for start in range(0, len(items), DB_BATCH_SIZE):
            chunk = items[start:start + DB_BATCH_SIZE]
            rows: list[dict] = []
            key_to_tools: dict[tuple, set[str]] = {}
            for key, data in chunk:
                asset = data["asset"]
                host = asset.host or host_of_url(asset.url)
                host_id = asset.host_id or (host_map.get(host) if host else None)
                key_to_tools[key] = data["tools"]
                rows.append({
                    "id": uuid.uuid4(),
                    "program_id": program.id,
                    "scope_id": scope.id,
                    "host_id": host_id,
                    "asset_id": asset.asset_id,
                    "asset_type": asset.asset_type,
                    "asset_url": asset.url,
                    "host": host[:255] if host else None,
                    "parameter_name": data["parameter_name"],
                    "parameter_type": data["parameter_type"],
                    "parameter_source": "ACTIVE",
                    "discovery_tools": sorted(data["tools"]),
                    "first_seen": now,
                    "last_seen": now,
                    "created_at": now,
                    "updated_at": now,
                })

            new_rows, existing_rows = self.param_repo.bulk_upsert(db, rows)
            metrics.new_parameters += len(new_rows)

            # Per-tool source attribution for every affected parameter.
            id_by_key = {
                (r["asset_id"], r["parameter_name"]): r["id"]
                for r in (new_rows + existing_rows)
            }
            source_rows: list[dict] = []
            for key, tools in key_to_tools.items():
                pid = id_by_key.get(key)
                if not pid:
                    continue
                for tool in tools:
                    source_rows.append({"parameter_id": pid, "tool_name": tool})
            self.param_repo.bulk_insert_sources(db, source_rows)

            # Counters — only NEW parameters contribute to host/subdomain rollups.
            host_deltas: dict[uuid.UUID, int] = {}
            name_deltas: dict[str, int] = {}
            for r in new_rows:
                hid = r.get("host_id")
                if hid:
                    host_deltas[hid] = host_deltas.get(hid, 0) + 1
                hn = r.get("host")
                if hn:
                    name_deltas[hn] = name_deltas.get(hn, 0) + 1
            self.host_repo.bulk_increment_parameter_counts(db, host_deltas)
            self.subdomain_repo.bulk_increment_parameter_counts(db, scope.id, name_deltas)

            # Per-asset parameter_count — set to the authoritative DB count for
            # each affected asset so re-runs stay correct (absolute, idempotent).
            self._sync_asset_counts(db, scope.id, chunk)

    def _sync_asset_counts(self, db, scope_id, chunk) -> None:
        """Recompute and store parameter_count on the affected url/endpoint rows."""
        url_ids: set[uuid.UUID] = set()
        endpoint_ids: set[uuid.UUID] = set()
        for (_key, data) in chunk:
            asset = data["asset"]
            if asset.asset_type == "URL":
                url_ids.add(asset.asset_id)
            else:
                endpoint_ids.add(asset.asset_id)
        for table, ids in (("urls", url_ids), ("endpoints", endpoint_ids)):
            if not ids:
                continue
            counts = {aid: self.param_repo.count_for_asset(db, scope_id, aid) for aid in ids}
            self.param_repo.bulk_set_asset_parameter_counts(db, table, counts)

    def _append_raw_artifacts(self, param_raw: Path, results: dict[str, list]) -> None:
        """Append raw per-tool findings to storage/.../parameters/raw/<tool>.json."""
        file_map = {ARJUN: "arjun.json", PARAMSPIDER: "paramspider.json"}
        for tool, findings in results.items():
            fname = file_map.get(tool, f"{tool.lower()}.json")
            target = param_raw / fname
            try:
                with target.open("a", encoding="utf-8") as fh:
                    for rp in findings:
                        fh.write(json.dumps({
                            "name": rp.name, "asset_url": rp.asset_url,
                            "confidence": rp.confidence,
                        }) + "\n")
            except OSError as exc:
                self.logger.warning("Failed writing raw artifact %s: %s", target, exc)

    def _persist_run_artifact(self, db, param_proc: Path, scope_id: uuid.UUID) -> None:
        """Write the merged parameter inventory artifact for the scope (streamed)."""
        target = param_proc / "merged_parameters.json"
        with target.open("w", encoding="utf-8") as fh:
            offset = 0
            page = 5_000
            while True:
                rows = self.param_repo.list_parameters(
                    db, scope_id=scope_id, offset=offset, limit=page, sort_by="parameter_name",
                )
                if not rows:
                    break
                for p in rows:
                    fh.write(json.dumps({
                        "parameter_name": p.parameter_name,
                        "parameter_type": p.parameter_type,
                        "asset_type": p.asset_type,
                        "asset_url": p.asset_url,
                        "host": p.host,
                        "discovery_tools": p.discovery_tools,
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
                command=f"{name.lower()} <dynamic assets>",
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
                arjun_count=tool_raw_counts.get(ARJUN, 0),
                paramspider_count=tool_raw_counts.get(PARAMSPIDER, 0),
                assets_scanned_count=metrics.assets_scanned,
                total_parameters_count=metrics.total_parameters,
                new_parameters_count=metrics.new_parameters,
            )
        )
        db.commit()

    def _build_tools(self) -> dict:
        """Instantiate every parameter-discovery tool. Register new tools here only.

        A future tool (ParamMiner, custom dictionary, AI module) only needs a
        wrapper implementing ``ParameterToolBase`` added to this dict — the worker
        body, DB schema and APIs need no change.
        """
        return {
            ARJUN: ArjunRunner(timeout=int(os.getenv("ARJUN_TIMEOUT", "600"))),
            PARAMSPIDER: ParamSpiderRunner(timeout=int(os.getenv("PARAMSPIDER_TIMEOUT", "600"))),
        }

    def _load_scan_data(self, db, scan_run_id: uuid.UUID):
        from backend.services.scan_run_service import ScanRunService
        svc = ScanRunService()
        scan_run = svc.get_scan_run(db=db, scan_run_id=scan_run_id)
        program = self.program_service.get_program(db=db, program_id=scan_run.program_id)
        scope = self.scope_service.get_scope(db=db, scope_id=scan_run.scope_id)
        return scan_run, program, scope


@celery_app.task(name="workers.parameter_discovery_worker.run_parameter_discovery_scan", bind=True)
def run_parameter_discovery_scan(self, scan_run_id: str) -> None:
    ParameterDiscoveryWorker().run_scan(scan_run_id)
