from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.schemas.stats_schema import GlobalStatsResponse
from database.models.enums import ProgramStatus, ScanStatus
from repositories.program_repository import ProgramRepository
from repositories.scan_run_repository import ScanRunRepository

router = APIRouter(
    prefix="/stats",
    tags=["Stats"],
)

_program_repo = ProgramRepository()
_scan_run_repo = ScanRunRepository()


@router.get("", response_model=GlobalStatsResponse)
def get_global_stats(
    db: Session = Depends(get_db),
) -> GlobalStatsResponse:
    """Aggregate dashboard statistics across all programs and scans."""
    total_programs = _program_repo.count(db, is_deleted=False)
    active_programs = _program_repo.count(
        db, is_deleted=False, status=ProgramStatus.ACTIVE.value
    )
    # "Inactive" = any program that is not active (paused or archived).
    inactive_programs = total_programs - active_programs

    running_scans = _scan_run_repo.count(db, status=ScanStatus.RUNNING.value)
    pending_scans = _scan_run_repo.count(db, status=ScanStatus.PENDING.value)

    return GlobalStatsResponse(
        total_programs=total_programs,
        active_programs=active_programs,
        inactive_programs=inactive_programs,
        running_scans=running_scans,
        pending_scans=pending_scans,
    )
