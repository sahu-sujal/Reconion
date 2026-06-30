from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.exceptions import EntityNotFoundError
from database.models.dns_record import DnsRecord
from database.models.host import Host
from database.models.js_file import JsFile
from database.models.program import Program
from database.models.scope import Scope
from database.models.asset import Asset
from database.models.finding import Finding
from database.models.notification import Notification
from database.models.scan_run import ScanRun
from database.models.subdomain import Subdomain
from database.models.technology import Technology
from database.models.url import URL
from database.models.enums import FindingStatus, ScanType

logger = logging.getLogger(__name__)


class ProgramService:
    """Service layer for program CRUD operations."""

    def create_program(
        self,
        db: Session,
        name: str,
        platform: str | None = None,
        description: str | None = None,
        created_by: str | None = None,
        status: str = "active",
    ) -> Program:
        program = Program(
            name=name,
            platform=platform,
            description=description,
            created_by=created_by,
            status=status,
        )
        db.add(program)
        db.commit()
        db.refresh(program)
        logger.info("Program created: %s", program.id)
        return program

    def get_program(self, db: Session, program_id: uuid.UUID) -> Program:
        program = db.get(Program, program_id)
        if program is None:
            raise EntityNotFoundError("Program", str(program_id))
        return program

    def list_programs(
        self,
        db: Session,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Program]:
        statement = select(Program).offset(offset).limit(limit)
        return db.scalars(statement).all()

    def list_scopes_for_program(
        self,
        db: Session,
        program_id: uuid.UUID,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Scope]:
        self.get_program(db, program_id)
        statement = select(Scope).filter(Scope.program_id == program_id)
        statement = statement.offset(offset).limit(limit)
        return db.scalars(statement).all()

    def get_program_stats(self, db: Session, program_id: uuid.UUID) -> dict[str, object]:
        self.get_program(db, program_id)

        total_scopes = db.scalar(
            select(func.count()).select_from(Scope).where(Scope.program_id == program_id)
        )
        active_scopes = db.scalar(
            select(func.count()).select_from(Scope).where(
                Scope.program_id == program_id,
                Scope.is_active == True,
            )
        )
        total_assets = db.scalar(
            select(func.count()).select_from(Asset).where(Asset.program_id == program_id)
        )
        total_findings = db.scalar(
            select(func.count()).select_from(Finding).where(Finding.program_id == program_id)
        )
        open_findings = db.scalar(
            select(func.count()).select_from(Finding).where(
                Finding.program_id == program_id,
                Finding.status != FindingStatus.CLOSED,
            )
        )
        total_scan_runs = db.scalar(
            select(func.count()).select_from(ScanRun).where(ScanRun.program_id == program_id)
        )
        total_notifications = db.scalar(
            select(func.count()).select_from(Notification).where(Notification.program_id == program_id)
        )
        last_scan_at = db.scalar(
            select(func.max(ScanRun.finished_at)).where(ScanRun.program_id == program_id)
        )
        last_notification_at = db.scalar(
            select(func.max(Notification.sent_at)).where(Notification.program_id == program_id)
        )

        total_subdomains = db.scalar(
            select(func.count()).select_from(Subdomain).where(Subdomain.program_id == program_id)
        )
        total_hosts = db.scalar(
            select(func.count()).select_from(Host).where(Host.program_id == program_id)
        )
        live_hosts = db.scalar(
            select(func.count()).select_from(Host).where(
                Host.program_id == program_id,
                Host.status_code.isnot(None),
            )
        )
        total_dns_records = db.scalar(
            select(func.count()).select_from(DnsRecord).where(DnsRecord.program_id == program_id)
        )
        total_technologies = db.scalar(
            select(func.count()).select_from(Technology).where(Technology.program_id == program_id)
        )

        # Content discovery (Phase 5) — totals are the true row counts (URLs for
        # out-of-scope/third-party hosts have host_id=NULL and would be missed by
        # SUM(hosts.url_count), so we count the tables directly). "new" comes from
        # the most recent content discovery scan run.
        total_urls = db.scalar(
            select(func.count()).select_from(URL).where(URL.program_id == program_id)
        )
        total_js = db.scalar(
            select(func.count()).select_from(JsFile).where(JsFile.program_id == program_id)
        )
        latest_cd = db.scalar(
            select(ScanRun)
            .where(
                ScanRun.program_id == program_id,
                ScanRun.scan_type == ScanType.CONTENT_DISCOVERY.value,
            )
            .order_by(ScanRun.started_at.desc())
            .limit(1)
        )
        new_urls = int(getattr(latest_cd, "new_urls_count", 0) or 0) if latest_cd else 0
        new_js = int(getattr(latest_cd, "new_js_count", 0) or 0) if latest_cd else 0

        return {
            "program_id": program_id,
            "total_scopes": int(total_scopes or 0),
            "active_scopes": int(active_scopes or 0),
            "total_assets": int(total_assets or 0),
            "total_subdomains": int(total_subdomains or 0),
            "total_hosts": int(total_hosts or 0),
            "live_hosts": int(live_hosts or 0),
            "total_dns_records": int(total_dns_records or 0),
            "total_technologies": int(total_technologies or 0),
            "total_urls": int(total_urls or 0),
            "new_urls": new_urls,
            "total_js_files": int(total_js or 0),
            "new_js_files": new_js,
            "total_findings": int(total_findings or 0),
            "open_findings": int(open_findings or 0),
            "total_scan_runs": int(total_scan_runs or 0),
            "total_notifications": int(total_notifications or 0),
            "last_scan_at": last_scan_at,
            "last_notification_at": last_notification_at,
        }

    def update_program(
        self,
        db: Session,
        program_id: uuid.UUID,
        name: str | None = None,
        platform: str | None = None,
        description: str | None = None,
        created_by: str | None = None,
        status: str | None = None,
    ) -> Program:
        program = self.get_program(db, program_id)
        if name is not None:
            program.name = name
        if platform is not None:
            program.platform = platform
        if description is not None:
            program.description = description
        if created_by is not None:
            program.created_by = created_by
        if status is not None:
            program.status = status
        db.commit()
        db.refresh(program)
        logger.info("Program updated: %s", program.id)
        return program

    def delete_program(self, db: Session, program_id: uuid.UUID) -> None:
        program = self.get_program(db, program_id)
        db.delete(program)
        db.commit()
        logger.info("Program deleted: %s", program_id)


class ScanRunService:
    """Service layer for scan run lifecycle management."""

    def create_scan_run(
        self,
        db: Session,
        program_id: uuid.UUID,
        scope_id: uuid.UUID,
        scan_type: str,
        worker_name: str,
        status: str,
        records_found: int = 0,
        error_message: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> ScanRun:
        scan_run_kwargs = {
            "program_id": program_id,
            "scope_id": scope_id,
            "scan_type": scan_type,
            "worker_name": worker_name,
            "status": status,
            "records_found": records_found,
            "error_message": error_message,
            "finished_at": finished_at,
        }
        if started_at is not None:
            scan_run_kwargs["started_at"] = started_at

        scan_run = ScanRun(**scan_run_kwargs)
        db.add(scan_run)
        db.commit()
        db.refresh(scan_run)
        logger.info("Scan run created: %s", scan_run.id)
        return scan_run

    def get_scan_run(self, db: Session, scan_run_id: uuid.UUID) -> ScanRun:
        scan_run = db.get(ScanRun, scan_run_id)
        if scan_run is None:
            raise EntityNotFoundError("ScanRun", str(scan_run_id))
        return scan_run

    def list_scan_runs(
        self,
        db: Session,
        program_id: uuid.UUID | None = None,
        scope_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[ScanRun]:
        statement = select(ScanRun)
        if program_id is not None:
            statement = statement.filter(ScanRun.program_id == program_id)
        if scope_id is not None:
            statement = statement.filter(ScanRun.scope_id == scope_id)
        statement = statement.offset(offset).limit(limit)
        return db.scalars(statement).all()

    def update_scan_run(
        self,
        db: Session,
        scan_run_id: uuid.UUID,
        status: str | None = None,
        records_found: int | None = None,
        error_message: str | None = None,
        finished_at: datetime | None = None,
    ) -> ScanRun:
        scan_run = self.get_scan_run(db, scan_run_id)
        if status is not None:
            scan_run.status = status
        if records_found is not None:
            scan_run.records_found = records_found
        if error_message is not None:
            scan_run.error_message = error_message
        if finished_at is not None:
            scan_run.finished_at = finished_at
        db.commit()
        db.refresh(scan_run)
        logger.info("Scan run updated: %s", scan_run.id)
        return scan_run


class StorageService:
    """Storage helpers for program and scope artifact management."""

    def __init__(self, root_path: str | Path | None = None) -> None:
        self.root_path = Path(root_path) if root_path is not None else Path(__file__).resolve().parents[2] / "storage"
        self.root_path = Path(os.getenv("STORAGE_ROOT", self.root_path))

    def get_program_path(self, program_id: uuid.UUID) -> Path:
        return self.root_path / "programs" / str(program_id)

    def get_scope_path(self, program_id: uuid.UUID, scope_id: uuid.UUID) -> Path:
        return self.get_program_path(program_id) / "scopes" / str(scope_id)

    def get_artifact_path(
        self,
        program_id: uuid.UUID,
        scope_id: uuid.UUID,
        artifact_category: str,
        artifact_name: str,
    ) -> Path:
        safe_category = artifact_category.replace("..", "").strip("/\\")
        safe_name = artifact_name.replace("..", "").strip("/\\")
        return self.get_scope_path(program_id, scope_id) / safe_category / safe_name

    def ensure_directory(self, path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create_program_storage(self, program_id: uuid.UUID) -> Path:
        path = self.get_program_path(program_id)
        return self.ensure_directory(path)

    def create_scope_storage(self, program_id: uuid.UUID, scope_id: uuid.UUID) -> Path:
        path = self.get_scope_path(program_id, scope_id)
        return self.ensure_directory(path)

    def save_artifact(
        self,
        program_id: uuid.UUID,
        scope_id: uuid.UUID,
        artifact_category: str,
        artifact_name: str,
        content: str | bytes,
        binary: bool = False,
    ) -> Path:
        artifact_path = self.get_artifact_path(program_id, scope_id, artifact_category, artifact_name)
        self.ensure_directory(artifact_path.parent)
        if binary:
            artifact_path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        else:
            artifact_path.write_text(content if isinstance(content, str) else str(content), encoding="utf-8")
        return artifact_path

    def load_artifact(
        self,
        program_id: uuid.UUID,
        scope_id: uuid.UUID,
        artifact_category: str,
        artifact_name: str,
        binary: bool = False,
    ) -> str | bytes:
        artifact_path = self.get_artifact_path(program_id, scope_id, artifact_category, artifact_name)
        if binary:
            return artifact_path.read_bytes()
        return artifact_path.read_text(encoding="utf-8")

    def list_artifacts(
        self,
        program_id: uuid.UUID,
        scope_id: uuid.UUID,
        artifact_category: str | None = None,
    ) -> list[Path]:
        scope_path = self.get_scope_path(program_id, scope_id)
        base_path = scope_path / artifact_category if artifact_category else scope_path
        if not base_path.exists():
            return []
        return [p for p in base_path.rglob("*") if p.is_file()]

    def get_scope_storage_location(self, program_id: uuid.UUID, scope_id: uuid.UUID) -> Path:
        return self.get_scope_path(program_id, scope_id)
