from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.exceptions import EntityNotFoundError, ScanLockedError
from backend.schemas.scan_schema import ScanReportResponse, ScanRunResponse, ScanStartRequest
from backend.schemas.subdomain_schema import SubdomainResponse
from backend.services.scan_service import ScanService

router = APIRouter(
    prefix="/scans",
    tags=["Scans"],
)

service = ScanService()


@router.post("/start", response_model=ScanRunResponse, status_code=status.HTTP_202_ACCEPTED)
def start_scan(
    payload: ScanStartRequest,
    db: Session = Depends(get_db),
) -> ScanRunResponse:
    """Start a new scan for a program and scope."""
    try:
        return service.start_scan(
            db=db,
            program_id=payload.program_id,
            scope_id=payload.scope_id,
            scan_type=payload.scan_type,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ScanLockedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=list[ScanRunResponse])
def list_scan_runs(
    program_id: uuid.UUID | None = None,
    scope_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
) -> list[ScanRunResponse]:
    """List scan runs, optionally filtered by program or scope."""
    return service.list_scan_runs(db=db, program_id=program_id, scope_id=scope_id)


@router.get("/{scan_run_id}", response_model=ScanRunResponse)
def get_scan_run(
    scan_run_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ScanRunResponse:
    """Get a scan run by ID."""
    try:
        return service.get_scan_run(db=db, scan_run_id=scan_run_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{scan_run_id}/subdomains", response_model=list[SubdomainResponse])
def get_scan_subdomains(
    scan_run_id: uuid.UUID,
    offset: int = Query(0, ge=0, description="Rows to skip"),
    limit: int = Query(2000, ge=1, le=10000, description="Max results to return"),
    after: str | None = Query(None, description="Keyset cursor: return rows after this subdomain"),
    db: Session = Depends(get_db),
) -> list[SubdomainResponse]:
    """List subdomains discovered during a scan (by scope), paginated."""
    try:
        return service.get_subdomains_for_scan(
            db=db,
            scan_run_id=scan_run_id,
            offset=offset,
            limit=limit,
            after_subdomain=after,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{scan_run_id}/report", response_model=ScanReportResponse)
def get_scan_report(
    scan_run_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ScanReportResponse:
    """Get a per-tool report for a scan: records found, duration, status."""
    try:
        return service.get_scan_report(db=db, scan_run_id=scan_run_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{scan_run_id}/pause", response_model=ScanRunResponse)
def pause_scan(
    scan_run_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ScanRunResponse:
    """Request a running scan to pause at its next safe boundary."""
    try:
        return service.pause_scan(db=db, scan_run_id=scan_run_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{scan_run_id}/resume", response_model=ScanRunResponse)
def resume_scan(
    scan_run_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ScanRunResponse:
    """Resume a paused scan from its stored checkpoint."""
    try:
        return service.resume_scan(db=db, scan_run_id=scan_run_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ScanLockedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{scan_run_id}/stop", response_model=ScanRunResponse)
def stop_scan(
    scan_run_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ScanRunResponse:
    """Stop (cancel) a running or paused scan. It can then be deleted."""
    try:
        return service.stop_scan(db=db, scan_run_id=scan_run_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/{scan_run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scan_run(
    scan_run_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> None:
    """Delete a completed, failed, cancelled, or paused scan. Rejects PENDING/RUNNING."""
    try:
        service.delete_scan(db=db, scan_run_id=scan_run_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
