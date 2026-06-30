from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.exceptions import EntityNotFoundError
from backend.schemas.program_schema import (
    ProgramCreate,
    ProgramResponse,
    ProgramStatsResponse,
    ProgramUpdate,
)
from backend.schemas.scope_schema import ScopeResponse
from backend.services.program_service import ProgramService

router = APIRouter(
    prefix="/programs",
    tags=["Programs"],
)

service = ProgramService()


@router.post("", response_model=ProgramResponse, status_code=status.HTTP_201_CREATED)
def create_program(
    payload: ProgramCreate,
    db: Session = Depends(get_db),
) -> ProgramResponse:
    """Create a new program."""
    return service.create_program(
        db=db,
        name=payload.name,
        platform=payload.platform,
        description=payload.description,
        created_by=payload.created_by,
        status=payload.status,
    )


@router.get("", response_model=list[ProgramResponse])
def list_programs(
    db: Session = Depends(get_db),
) -> list[ProgramResponse]:
    """List all programs."""
    return service.list_programs(db=db)


@router.get("/{program_id}", response_model=ProgramResponse)
def get_program(
    program_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ProgramResponse:
    """Get a program by ID."""
    try:
        return service.get_program(db=db, program_id=program_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{program_id}", response_model=ProgramResponse)
def update_program(
    program_id: uuid.UUID,
    payload: ProgramUpdate,
    db: Session = Depends(get_db),
) -> ProgramResponse:
    """Update program metadata."""
    try:
        return service.update_program(
            db=db,
            program_id=program_id,
            name=payload.name,
            platform=payload.platform,
            description=payload.description,
            created_by=payload.created_by,
            status=payload.status,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{program_id}/scopes", response_model=list[ScopeResponse])
def list_program_scopes(
    program_id: uuid.UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=250),
    db: Session = Depends(get_db),
) -> list[ScopeResponse]:
    """List scopes that belong to a program."""
    try:
        return service.list_scopes_for_program(db=db, program_id=program_id, offset=offset, limit=limit)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{program_id}/stats", response_model=ProgramStatsResponse)
def get_program_stats(
    program_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ProgramStatsResponse:
    """Get summary statistics for a program."""
    try:
        return service.get_program_stats(db=db, program_id=program_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{program_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_program(
    program_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> None:
    """Delete a program by ID."""
    try:
        service.delete_program(db=db, program_id=program_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
