"""Asset Explorer API (Phase 6.3).

Serves the unified, classified asset inventory — the tool-agnostic replacement
for the old separate URL / Endpoint listings:

    GET /scopes/{scope_id}/assets            categorized, searchable, filtered list
    GET /scopes/{scope_id}/asset-stats       total + per-category counts (+ meta)
    GET /scopes/{scope_id}/asset-hosts        host filter facet
    GET /scopes/{scope_id}/asset-extensions   extension filter facet
    GET /asset-categories                     taxonomy metadata (sidebar order)

All classification is precomputed by the Asset Classification Engine; these
routes only read the ``asset_inventory`` view (no network, no reclassification).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.exceptions import EntityNotFoundError
from backend.schemas.asset_schema import (
    AssetResponse,
    AssetStatsResponse,
    CategoryMetaResponse,
    PaginatedAssets,
)
from backend.services.scope_service import ScopeService
from repositories.asset_inventory_repository import AssetInventoryRepository
from tools.common.asset_classifier import JAVASCRIPT, all_categories

router = APIRouter(tags=["Assets"])

_scope_service = ScopeService()
_asset_repo = AssetInventoryRepository()


def _ensure_scope(db: Session, scope_id: uuid.UUID) -> None:
    try:
        _scope_service.get_scope(db=db, scope_id=scope_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/asset-categories", response_model=list[CategoryMetaResponse])
def get_asset_categories() -> list[CategoryMetaResponse]:
    """The classification taxonomy (stable order) — drives the Explorer sidebar."""
    return [CategoryMetaResponse(**c) for c in all_categories()]


@router.get("/scopes/{scope_id}/assets", response_model=PaginatedAssets)
def get_scope_assets(
    scope_id: uuid.UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
    category: str | None = Query(None, description="Filter by asset_category (API, JAVASCRIPT, …)"),
    search: str | None = Query(None, description="Global substring match on URL or host"),
    host: str | None = Query(None, description="Host filter (matches host + its subdomains)"),
    extension: str | None = Query(None, description="Exact extension filter (pdf, zip, …)"),
    source_kind: str | None = Query(None, description="URL | ENDPOINT | JS"),
    discovery_source: str | None = Query(None, description="Discovery source substring"),
    trait: str | None = Query(None, description="Boolean trait filter (is_api, is_backup, …)"),
    sort_by: str = Query("normalized_url"),
    sort_dir: str = Query("asc"),
    db: Session = Depends(get_db),
) -> PaginatedAssets:
    """List classified assets for a scope (categorized, searchable, filterable)."""
    _ensure_scope(db, scope_id)

    filters = dict(
        scope_id=scope_id, category=category, search=search, host=host,
        extension=extension, source_kind=source_kind,
        discovery_source=discovery_source, trait=trait,
    )
    rows = _asset_repo.list_assets(
        db, offset=offset, limit=limit, sort_by=sort_by, sort_dir=sort_dir, **filters,
    )
    total = _asset_repo.count_assets(db, **filters)

    # JS category enrichment: size + endpoints extracted + secrets found.
    js_rows = [r for r in rows if r.get("asset_category") == JAVASCRIPT]
    if js_rows:
        enrich = _asset_repo.enrich_js(db, scope_id, [r["normalized_url"] for r in js_rows])
        for r in js_rows:
            extra = enrich.get(r["normalized_url"])
            if extra:
                r.update(extra)

    items = [AssetResponse(**r) for r in rows]
    return PaginatedAssets(total=total, offset=offset, limit=limit, items=items)


@router.get("/scopes/{scope_id}/asset-stats", response_model=AssetStatsResponse)
def get_scope_asset_stats(
    scope_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> AssetStatsResponse:
    """Dashboard/sidebar asset statistics: total + per-category counts + meta."""
    _ensure_scope(db, scope_id)
    by_category = _asset_repo.category_counts(db, scope_id=scope_id)
    total = sum(by_category.values())
    return AssetStatsResponse(
        total_assets=total,
        by_category=by_category,
        categories=[CategoryMetaResponse(**c) for c in all_categories()],
    )


@router.get("/scopes/{scope_id}/asset-hosts", response_model=list[str])
def get_scope_asset_hosts(
    scope_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> list[str]:
    """Distinct hosts across all asset categories (filter dropdown)."""
    _ensure_scope(db, scope_id)
    return _asset_repo.distinct_hosts(db, scope_id=scope_id)


@router.get("/scopes/{scope_id}/asset-extensions", response_model=list[str])
def get_scope_asset_extensions(
    scope_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> list[str]:
    """Distinct extensions across all asset categories (filter dropdown)."""
    _ensure_scope(db, scope_id)
    return _asset_repo.distinct_extensions(db, scope_id=scope_id)
