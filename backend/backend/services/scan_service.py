from __future__ import annotations

import uuid

from backend.celery_app import celery_app
from backend.exceptions import EntityNotFoundError, ScanLockedError
from backend.queues.redis_client import acquire_scope_lock, is_scope_locked, release_scope_lock
from backend.services.program_service import ProgramService
from backend.services.scope_service import ScopeService
from backend.services.scan_run_service import ScanRunService
from database.models.enums import ScanStatus, ScanType
from repositories.subdomain_repository import SubdomainRepository
from repositories.tool_execution_repository import ToolExecutionRepository


class ScanService:
    def __init__(self) -> None:
        self.program_service = ProgramService()
        self.scope_service = ScopeService()
        self.scan_run_service = ScanRunService()
        self.subdomain_repo = SubdomainRepository()
        self.tool_execution_repo = ToolExecutionRepository()

    # scan_type → (celery task name, worker_name)
    _SCAN_TASK_MAP = {
        ScanType.SUBDOMAIN.value: (
            "workers.subdomain.subdomain_worker.run_subdomain_scan",
            "subdomain_worker",
        ),
        ScanType.DNS.value: (
            "workers.dns.dns_worker.run_dns_scan",
            "dns_worker",
        ),
        ScanType.HTTP.value: (
            "workers.http.http_worker.run_http_scan",
            "http_worker",
        ),
        ScanType.CONTENT_DISCOVERY.value: (
            "workers.url.url_worker.run_url_scan",
            "url_worker",
        ),
    }

    def start_scan(
        self,
        db,
        program_id: uuid.UUID,
        scope_id: uuid.UUID,
        scan_type: str = ScanType.SUBDOMAIN.value,
    ):
        self.program_service.get_program(db=db, program_id=program_id)
        scope = self.scope_service.get_scope(db=db, scope_id=scope_id)

        if scan_type not in self._SCAN_TASK_MAP:
            raise ValueError(f"Unsupported scan_type for direct start: {scan_type}")

        if not acquire_scope_lock(scope_id):
            if is_scope_locked(scope_id):
                latest_scan = self.scan_run_service.get_latest_scan_by_scope(db=db, scope_id=scope_id)
                if latest_scan is not None and latest_scan.status not in (
                    ScanStatus.PENDING.value,
                    ScanStatus.RUNNING.value,
                ):
                    release_scope_lock(scope_id)
                    if not acquire_scope_lock(scope_id):
                        raise ScanLockedError(str(scope_id))
                else:
                    raise ScanLockedError(str(scope_id))
            else:
                raise ScanLockedError(str(scope_id))

        task_name, worker_name = self._SCAN_TASK_MAP[scan_type]
        try:
            scan_run = self.scan_run_service.create_scan_run(
                db=db,
                program_id=program_id,
                scope_id=scope_id,
                scan_type=scan_type,
                worker_name=worker_name,
                status=ScanStatus.PENDING.value,
            )

            celery_app.send_task(task_name, args=[str(scan_run.id)], countdown=1)
            scan_run.target = scope.target
            return scan_run
        except Exception:
            release_scope_lock(scope_id)
            raise

    def get_scan_run(self, db, scan_run_id: uuid.UUID):
        scan_run = self.scan_run_service.get_scan_run(db=db, scan_run_id=scan_run_id)
        scan_run.target = scan_run.scope.target if scan_run.scope else None
        return scan_run

    def list_scan_runs(self, db, program_id: uuid.UUID | None = None, scope_id: uuid.UUID | None = None):
        scan_runs = self.scan_run_service.list_scan_runs(db=db, program_id=program_id, scope_id=scope_id)
        for scan_run in scan_runs:
            scan_run.target = scan_run.scope.target if scan_run.scope else None
        return scan_runs

    def delete_scan(self, db, scan_run_id: uuid.UUID) -> None:
        scan_run = self.scan_run_service.get_scan_run(db, scan_run_id)
        if scan_run.status in (ScanStatus.PENDING.value, ScanStatus.RUNNING.value):
            raise ValueError(
                f"Cannot delete a scan in '{scan_run.status}' state. "
                "Only COMPLETED, FAILED, or CANCELLED scans can be deleted."
            )
        self.scan_run_service.repo.delete(db, scan_run)

    def get_subdomains_for_scan(
        self,
        db,
        scan_run_id: uuid.UUID,
        offset: int = 0,
        limit: int = 2000,
        after_subdomain: str | None = None,
    ):
        scan_run = self.scan_run_service.get_scan_run(db, scan_run_id)
        return self.subdomain_repo.list_by_scope(
            db,
            scan_run.scope_id,
            offset=offset,
            limit=limit,
            after_subdomain=after_subdomain,
        )

    def get_scan_report(self, db, scan_run_id: uuid.UUID):
        from backend.schemas.scan_schema import ScanReportResponse, ToolExecutionSummary

        scan_run = self.scan_run_service.get_scan_run(db, scan_run_id)
        tool_executions = self.tool_execution_repo.list_by_scan_run(db, scan_run_id)
        tools = [ToolExecutionSummary.model_validate(te) for te in tool_executions]

        return ScanReportResponse(
            id=scan_run.id,
            program_id=scan_run.program_id,
            scope_id=scan_run.scope_id,
            target=scan_run.scope.target if scan_run.scope else None,
            scan_type=str(scan_run.scan_type),
            status=str(scan_run.status),
            records_found=scan_run.records_found,
            # Subdomain counters
            subfinder_count=getattr(scan_run, "subfinder_count", 0) or 0,
            assetfinder_count=getattr(scan_run, "assetfinder_count", 0) or 0,
            merged_count=getattr(scan_run, "merged_count", 0) or 0,
            unique_count=getattr(scan_run, "unique_count", 0) or 0,
            new_count=getattr(scan_run, "new_count", 0) or 0,
            existing_count=getattr(scan_run, "existing_count", 0) or 0,
            # DNS counters
            dnsx_count=getattr(scan_run, "dnsx_count", 0) or 0,
            resolved_count=getattr(scan_run, "resolved_count", 0) or 0,
            new_hosts_count=getattr(scan_run, "new_hosts_count", 0) or 0,
            # HTTP counters
            httpx_count=getattr(scan_run, "httpx_count", 0) or 0,
            live_count=getattr(scan_run, "live_count", 0) or 0,
            new_live_count=getattr(scan_run, "new_live_count", 0) or 0,
            # Content discovery counters
            gau_count=getattr(scan_run, "gau_count", 0) or 0,
            waybackurls_count=getattr(scan_run, "waybackurls_count", 0) or 0,
            katana_count=getattr(scan_run, "katana_count", 0) or 0,
            hakrawler_count=getattr(scan_run, "hakrawler_count", 0) or 0,
            total_urls_count=getattr(scan_run, "total_urls_count", 0) or 0,
            new_urls_count=getattr(scan_run, "new_urls_count", 0) or 0,
            total_js_count=getattr(scan_run, "total_js_count", 0) or 0,
            new_js_count=getattr(scan_run, "new_js_count", 0) or 0,
            error_message=scan_run.error_message,
            started_at=scan_run.started_at,
            finished_at=scan_run.finished_at,
            tools=tools,
        )
