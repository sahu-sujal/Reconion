from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.exceptions import EntityNotFoundError
from backend.schemas.host_schema import (
    DnsRecordResponse,
    HostResponse,
    HttpResponseResponse,
    TechnologyResponse,
)
from backend.schemas.scope_schema import (
    ScopeCreate,
    ScopeResponse,
    ScopeStatsResponse,
    ScopeUpdate,
)
from backend.schemas.subdomain_schema import SubdomainResponse
from backend.schemas.url_schema import PaginatedJsFiles, PaginatedUrls
from backend.services.scope_service import ScopeService
from repositories.dns_record_repository import DnsRecordRepository
from repositories.host_repository import HostRepository
from repositories.http_response_repository import HttpResponseRepository
from repositories.js_file_repository import JsFileRepository
from repositories.subdomain_repository import SubdomainRepository
from repositories.technology_repository import TechnologyRepository
from repositories.url_repository import URLRepository

router = APIRouter(
    prefix="/scopes",
    tags=["Scopes"],
)

service = ScopeService()
_subdomain_repo = SubdomainRepository()
_host_repo = HostRepository()
_dns_record_repo = DnsRecordRepository()
_http_response_repo = HttpResponseRepository()
_technology_repo = TechnologyRepository()
_url_repo = URLRepository()
_js_file_repo = JsFileRepository()


@router.post("", response_model=ScopeResponse, status_code=status.HTTP_201_CREATED)
def create_scope(
    payload: ScopeCreate,
    db: Session = Depends(get_db),
) -> ScopeResponse:
    """Create a new scope for a program."""
    try:
        return service.create_scope(
            db=db,
            program_id=payload.program_id,
            target=payload.target,
            scope_type=payload.scope_type,
            priority=payload.priority,
            is_active=payload.is_active,
            notes=payload.notes,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=list[ScopeResponse])
def list_scopes(
    program_id: uuid.UUID | None = Query(None, description="Optional program ID filter"),
    db: Session = Depends(get_db),
) -> list[ScopeResponse]:
    """List all scopes, optionally filtering by program."""
    return service.list_scopes(db=db, program_id=program_id)


@router.get("/{scope_id}", response_model=ScopeResponse)
def get_scope(
    scope_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ScopeResponse:
    """Get a scope by ID."""
    try:
        return service.get_scope(db=db, scope_id=scope_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{scope_id}", response_model=ScopeResponse)
def update_scope(
    scope_id: uuid.UUID,
    payload: ScopeUpdate,
    db: Session = Depends(get_db),
) -> ScopeResponse:
    """Update scope metadata."""
    try:
        return service.update_scope(
            db=db,
            scope_id=scope_id,
            scope_type=payload.scope_type,
            priority=payload.priority,
            is_active=payload.is_active,
            notes=payload.notes,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{scope_id}/stats", response_model=ScopeStatsResponse)
def get_scope_stats(
    scope_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ScopeStatsResponse:
    """Get summary statistics for a scope."""
    try:
        return service.get_scope_stats(db=db, scope_id=scope_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{scope_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scope(
    scope_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> None:
    """Delete a scope by ID."""
    try:
        service.delete_scope(db=db, scope_id=scope_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{scope_id}/subdomains", response_model=list[SubdomainResponse])
def get_scope_subdomains(
    scope_id: uuid.UUID,
    offset: int = Query(0, ge=0, description="Rows to skip"),
    limit: int = Query(2000, ge=1, le=10000, description="Max results to return"),
    after: str | None = Query(None, description="Keyset cursor: return rows after this subdomain"),
    db: Session = Depends(get_db),
) -> list[SubdomainResponse]:
    """List all subdomains discovered for a scope."""
    try:
        service.get_scope(db=db, scope_id=scope_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _subdomain_repo.list_by_scope(
        db, scope_id, offset=offset, limit=limit, after_subdomain=after,
    )


@router.get("/{scope_id}/hosts", response_model=list[HostResponse])
def get_scope_hosts(
    scope_id: uuid.UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(2000, ge=1, le=10000),
    after: str | None = Query(None, description="Keyset cursor: host FQDN after which to return"),
    live_only: bool = Query(False, description="Return only hosts with an HTTP status code"),
    db: Session = Depends(get_db),
) -> list[HostResponse]:
    """List all resolved hosts for a scope."""
    try:
        service.get_scope(db=db, scope_id=scope_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if live_only:
        return _host_repo.list_live_by_scope(db, scope_id, offset=offset, limit=limit)
    return _host_repo.list_by_scope(db, scope_id, offset=offset, limit=limit, after_host=after)


@router.get("/{scope_id}/dns-records", response_model=list[DnsRecordResponse])
def get_scope_dns_records(
    scope_id: uuid.UUID,
    record_type: str | None = Query(None, description="Filter by record type (A, AAAA, CNAME, MX, TXT, NS)"),
    offset: int = Query(0, ge=0),
    limit: int = Query(2000, ge=1, le=10000),
    db: Session = Depends(get_db),
) -> list[DnsRecordResponse]:
    """List DNS records discovered for a scope."""
    try:
        service.get_scope(db=db, scope_id=scope_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _dns_record_repo.list_by_scope(
        db, scope_id, record_type=record_type, offset=offset, limit=limit,
    )


@router.get("/{scope_id}/http-responses", response_model=list[HttpResponseResponse])
def get_scope_http_responses(
    scope_id: uuid.UUID,
    status_code: int | None = Query(None, description="Filter by HTTP status code"),
    offset: int = Query(0, ge=0),
    limit: int = Query(2000, ge=1, le=10000),
    db: Session = Depends(get_db),
) -> list[HttpResponseResponse]:
    """List HTTP responses for all live hosts in a scope."""
    try:
        service.get_scope(db=db, scope_id=scope_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _http_response_repo.list_by_scope(
        db, scope_id, status_code=status_code, offset=offset, limit=limit,
    )


@router.get("/{scope_id}/technologies", response_model=list[TechnologyResponse])
def get_scope_technologies(
    scope_id: uuid.UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(2000, ge=1, le=10000),
    db: Session = Depends(get_db),
) -> list[TechnologyResponse]:
    """List all detected technologies for a scope."""
    try:
        service.get_scope(db=db, scope_id=scope_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _technology_repo.list(db, offset=offset, limit=limit, scope_id=scope_id)


@router.get("/{scope_id}/urls", response_model=PaginatedUrls)
def get_scope_urls(
    scope_id: uuid.UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(2000, ge=1, le=10000),
    search: str | None = Query(None, description="Substring match on normalized URL"),
    source: str | None = Query(None, description="Filter by discovery tool (GAU, KATANA…)"),
    host: str | None = Query(None, description="Exact host filter (e.g. api.example.com)"),
    sort_by: str = Query("normalized_url", description="Column to sort by"),
    sort_dir: str = Query("asc", description="asc or desc"),
    db: Session = Depends(get_db),
) -> PaginatedUrls:
    """List discovered URLs for a scope (paginated, searchable, sortable)."""
    try:
        service.get_scope(db=db, scope_id=scope_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    items = _url_repo.list_by_scope(
        db, scope_id, offset=offset, limit=limit,
        search=search, source=source, host=host, sort_by=sort_by, sort_dir=sort_dir,
    )
    total = _url_repo.count_by_scope(db, scope_id, search=search, source=source, host=host)
    return PaginatedUrls(total=total, offset=offset, limit=limit, items=items)


@router.get("/{scope_id}/url-hosts", response_model=list[str])
def get_scope_url_hosts(
    scope_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> list[str]:
    """Return the sorted unique list of hosts that have discovered URLs.

    Used by the frontend to build the host filter dropdown.
    """
    try:
        service.get_scope(db=db, scope_id=scope_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _url_repo.distinct_hosts_by_scope(db, scope_id)


@router.get("/{scope_id}/js-files", response_model=PaginatedJsFiles)
def get_scope_js_files(
    scope_id: uuid.UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(2000, ge=1, le=10000),
    search: str | None = Query(None, description="Substring match on JS URL"),
    host: str | None = Query(None, description="Exact host filter (e.g. api.example.com)"),
    sort_by: str = Query("url", description="Column to sort by"),
    sort_dir: str = Query("asc", description="asc or desc"),
    db: Session = Depends(get_db),
) -> PaginatedJsFiles:
    """List discovered JavaScript files for a scope (paginated, searchable)."""
    try:
        service.get_scope(db=db, scope_id=scope_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    items = _js_file_repo.list_by_scope(
        db, scope_id, offset=offset, limit=limit,
        search=search, host=host, sort_by=sort_by, sort_dir=sort_dir,
    )
    total = _js_file_repo.count_by_scope(db, scope_id, search=search, host=host)
    return PaginatedJsFiles(total=total, offset=offset, limit=limit, items=items)
