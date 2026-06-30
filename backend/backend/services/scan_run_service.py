from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from backend.exceptions import EntityNotFoundError
from database.models.scan_run import ScanRun
from repositories.scan_run_repository import ScanRunRepository


class ScanRunService:
    def __init__(self) -> None:
        self.repo = ScanRunRepository()

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
        return self.repo.create(
            db,
            program_id=program_id,
            scope_id=scope_id,
            scan_type=scan_type,
            worker_name=worker_name,
            status=status,
            records_found=records_found,
            error_message=error_message,
            started_at=started_at,
            finished_at=finished_at,
        )

    def get_scan_run(self, db: Session, scan_run_id: uuid.UUID) -> ScanRun:
        scan_run = self.repo.get(db, scan_run_id)
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
        filters = {}
        if program_id is not None:
            filters["program_id"] = program_id
        if scope_id is not None:
            filters["scope_id"] = scope_id
        return self.repo.list(db, offset=offset, limit=limit, **filters)

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
        updates = {}
        if status is not None:
            updates["status"] = status
        if records_found is not None:
            updates["records_found"] = records_found
        if error_message is not None:
            updates["error_message"] = error_message
        if finished_at is not None:
            updates["finished_at"] = finished_at
        return self.repo.update(db, scan_run, **updates)

    def get_latest_scan_by_scope(self, db: Session, scope_id: uuid.UUID) -> ScanRun | None:
        return self.repo.get_latest_by_scope(db, scope_id)
