"""Endpoint inventory API (Phase 6.1).

Exposes the unified endpoint inventory with search, pagination and sorting:

    GET /subdomains/{subdomain_id}/endpoints   endpoints for one subdomain FQDN
    GET /scopes/{scope_id}/endpoints           all endpoints in a scope
    GET /scopes/{scope_id}/endpoint-stats      dashboard counters
    GET /scopes/{scope_id}/endpoint-hosts      host filter dropdown values
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.exceptions import EntityNotFoundError
from backend.schemas.endpoint_schema import (
    EndpointStatsResponse,
    PaginatedEndpoints,
)
from backend.services.scope_service import ScopeService
from repositories.endpoint_repository import EndpointRepository
from repositories.subdomain_repository import SubdomainRepository

router = APIRouter(tags=["Endpoints"])

_scope_service = ScopeService()
_endpoint_repo = EndpointRepository()
_subdomain_repo = SubdomainRepository()


@router.get("/subdomains/{subdomain_id}/endpoints", response_model=PaginatedEndpoints)
def get_subdomain_endpoints(
    subdomain_id: uuid.UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(2000, ge=1, le=10000),
    search: str | None = Query(None, description="Match on URL, path, or host"),
    tool: str | None = Query(None, description="Filter by discovery tool (LINKFINDER, JSLUICE…)"),
    source_js: str | None = Query(None, description="Filter by originating JS file URL"),
    sort_by: str = Query("normalized_url", description="Column to sort by"),
    sort_dir: str = Query("asc", description="asc or desc"),
    db: Session = Depends(get_db),
) -> PaginatedEndpoints:
    """List endpoints discovered for a single subdomain (paginated/searchable)."""
    subdomain = _subdomain_repo.get(db, subdomain_id)
    if subdomain is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subdomain not found")

    items = _endpoint_repo.list_by_host_value(
        db, subdomain.scope_id, subdomain.subdomain,
        offset=offset, limit=limit, search=search, tool=tool,
        source_js=source_js, sort_by=sort_by, sort_dir=sort_dir,
    )
    total = _endpoint_repo.count_by_host_value(
        db, subdomain.scope_id, subdomain.subdomain,
        search=search, tool=tool, source_js=source_js,
    )
    return PaginatedEndpoints(total=total, offset=offset, limit=limit, items=items)


@router.get("/scopes/{scope_id}/endpoints", response_model=PaginatedEndpoints)
def get_scope_endpoints(
    scope_id: uuid.UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(2000, ge=1, le=10000),
    search: str | None = Query(None, description="Match on URL, path, or host"),
    host: str | None = Query(None, description="Host filter (e.g. api.example.com)"),
    tool: str | None = Query(None, description="Filter by discovery tool"),
    source_js: str | None = Query(None, description="Filter by originating JS file URL"),
    sort_by: str = Query("normalized_url", description="Column to sort by"),
    sort_dir: str = Query("asc", description="asc or desc"),
    db: Session = Depends(get_db),
) -> PaginatedEndpoints:
    """List all endpoints for a scope (paginated, searchable, sortable)."""
    try:
        _scope_service.get_scope(db=db, scope_id=scope_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    items = _endpoint_repo.list_by_scope(
        db, scope_id, offset=offset, limit=limit, search=search, host=host,
        tool=tool, source_js=source_js, sort_by=sort_by, sort_dir=sort_dir,
    )
    total = _endpoint_repo.count_by_scope(
        db, scope_id, search=search, host=host, tool=tool, source_js=source_js,
    )
    return PaginatedEndpoints(total=total, offset=offset, limit=limit, items=items)


@router.get("/scopes/{scope_id}/endpoint-stats", response_model=EndpointStatsResponse)
def get_scope_endpoint_stats(
    scope_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> EndpointStatsResponse:
    """Dashboard counters: total, new (24h), per-host and per-subdomain."""
    try:
        _scope_service.get_scope(db=db, scope_id=scope_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    from datetime import datetime, timedelta, timezone

    total = _endpoint_repo.count_for_scope(db, scope_id)
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    new = _endpoint_repo.new_endpoints_since(db, scope_id, since)
    per_host = _endpoint_repo.endpoints_per_host(db, scope_id)
    # "Per subdomain" and "per host" are the same key space here (a host's name
    # is its subdomain FQDN); exposed under both names for the dashboard.
    return EndpointStatsResponse(
        total_endpoints=total,
        new_endpoints=new,
        endpoints_per_host=per_host,
        endpoints_per_subdomain=per_host,
    )


@router.get("/scopes/{scope_id}/endpoint-hosts", response_model=list[str])
def get_scope_endpoint_hosts(
    scope_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> list[str]:
    """Sorted unique hosts that have at least one endpoint (filter dropdown)."""
    try:
        _scope_service.get_scope(db=db, scope_id=scope_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return sorted(_endpoint_repo.endpoints_per_host(db, scope_id, limit=100000).keys())
