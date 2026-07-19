"""GF Intelligence API — browse recon results by security relevance.

All listing endpoints are server-side: filtering, searching, sorting and
pagination happen in SQL so the frontend never loads the full inventory.
"""
from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.schemas.gf_schema import (
    GfAssetResponse,
    GfCategoryResponse,
    GfScanQueueRequest,
    GfScanQueueResponse,
    GfStatisticsResponse,
    PaginatedGfAssets,
)
from repositories.gf_repository import GfRepository
from tools.gf.gf_matcher import available_categories

router = APIRouter(prefix="/gf", tags=["GF Intelligence"])

_repo = GfRepository()

#: Queued scan requests live in memory until an active-scanning phase exists.
#: Exposed so the frontend's bulk actions have a real endpoint to call today.
_SCAN_QUEUE: list[dict] = []

_EXPORT_COLUMNS = [
    "url", "host", "asset_type", "gf_tags",
    "program_id", "scope_id", "gf_classified_at",
]


def _filters(
    program_id: list[uuid.UUID] | None,
    scope_id: list[uuid.UUID] | None,
    host: list[str] | None,
    asset_type: list[str] | None,
    category: list[str] | None,
    match_all: bool,
    only_matched: bool,
    search: str | None,
) -> dict:
    return {
        "program_ids": program_id or None,
        "scope_ids": scope_id or None,
        "hosts": host or None,
        "asset_types": [a.upper() for a in asset_type] if asset_type else None,
        "categories": category or None,
        "match_all": match_all,
        "only_matched": only_matched,
        "search": search,
    }


@router.get("/categories", response_model=list[GfCategoryResponse])
def list_gf_categories(
    program_id: list[uuid.UUID] | None = Query(None),
    scope_id: list[uuid.UUID] | None = Query(None),
    include_empty: bool = Query(
        False, description="Also list compiled categories with zero matches",
    ),
    db: Session = Depends(get_db),
) -> list[GfCategoryResponse]:
    """Every GF category present in the data, with asset counts.

    Generated from stored tags — never hardcoded. ``include_empty`` additionally
    lists categories the pattern set can produce but which nothing matched yet.
    """
    rows = _repo.list_categories(
        db, program_ids=program_id or None, scope_ids=scope_id or None,
    )
    if include_empty:
        seen = {r["category"] for r in rows}
        for name in available_categories():
            if name not in seen:
                rows.append({
                    "category": name, "asset_count": 0,
                    "url_count": 0, "endpoint_count": 0, "host_count": 0,
                })
    return [GfCategoryResponse(**r) for r in rows]


@router.get("/categories/{category}", response_model=PaginatedGfAssets)
def get_gf_category_assets(
    category: str,
    program_id: list[uuid.UUID] | None = Query(None),
    scope_id: list[uuid.UUID] | None = Query(None),
    host: list[str] | None = Query(None),
    asset_type: list[str] | None = Query(None),
    search: str | None = Query(None),
    sort_by: str = Query("gf_tag_count"),
    sort_dir: str = Query("desc"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> PaginatedGfAssets:
    """Every asset tagged with one GF category (paginated)."""
    filters = _filters(
        program_id, scope_id, host, asset_type, [category],
        match_all=False, only_matched=True, search=search,
    )
    items = _repo.list_assets(
        db, sort_by=sort_by, sort_dir=sort_dir, offset=offset, limit=limit, **filters,
    )
    total = _repo.count_assets(db, **filters)
    return PaginatedGfAssets(
        total=total, offset=offset, limit=limit,
        items=[GfAssetResponse(**i) for i in items],
    )


@router.get("/assets", response_model=PaginatedGfAssets)
def list_gf_assets(
    program_id: list[uuid.UUID] | None = Query(None),
    scope_id: list[uuid.UUID] | None = Query(None),
    host: list[str] | None = Query(None),
    asset_type: list[str] | None = Query(None, description="URL and/or ENDPOINT"),
    category: list[str] | None = Query(None, description="GF categories (multi-select)"),
    match_all: bool = Query(False, description="Require ALL categories instead of any"),
    only_matched: bool = Query(True, description="Only assets with >=1 GF tag"),
    search: str | None = Query(None, description="Substring match on URL or host"),
    sort_by: str = Query("gf_tag_count"),
    sort_dir: str = Query("desc"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> PaginatedGfAssets:
    """Browse GF-classified assets with server-side filter/sort/paginate."""
    filters = _filters(
        program_id, scope_id, host, asset_type, category,
        match_all, only_matched, search,
    )
    items = _repo.list_assets(
        db, sort_by=sort_by, sort_dir=sort_dir, offset=offset, limit=limit, **filters,
    )
    total = _repo.count_assets(db, **filters)
    return PaginatedGfAssets(
        total=total, offset=offset, limit=limit,
        items=[GfAssetResponse(**i) for i in items],
    )


@router.get("/hosts", response_model=list[str])
def list_gf_hosts(
    program_id: list[uuid.UUID] | None = Query(None),
    scope_id: list[uuid.UUID] | None = Query(None),
    db: Session = Depends(get_db),
) -> list[str]:
    """Hosts with at least one GF-tagged asset — for the host filter dropdown."""
    return _repo.distinct_hosts(
        db, program_ids=program_id or None, scope_ids=scope_id or None,
    )


@router.get("/statistics", response_model=GfStatisticsResponse)
def get_gf_statistics(
    program_id: list[uuid.UUID] | None = Query(None),
    scope_id: list[uuid.UUID] | None = Query(None),
    top: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> GfStatisticsResponse:
    """Dashboard aggregates for the GF Intelligence landing page."""
    return GfStatisticsResponse(**_repo.statistics(
        db, program_ids=program_id or None, scope_ids=scope_id or None, top=top,
    ))


@router.get("/export")
def export_gf_assets(
    fmt: str = Query("csv", pattern="^(csv|json)$"),
    program_id: list[uuid.UUID] | None = Query(None),
    scope_id: list[uuid.UUID] | None = Query(None),
    host: list[str] | None = Query(None),
    asset_type: list[str] | None = Query(None),
    category: list[str] | None = Query(None),
    match_all: bool = Query(False),
    only_matched: bool = Query(True),
    search: str | None = Query(None),
    limit: int = Query(50_000, ge=1, le=200_000),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Export the current filter selection as CSV or JSON.

    Streamed in pages so a large export never materializes in memory.
    """
    filters = _filters(
        program_id, scope_id, host, asset_type, category,
        match_all, only_matched, search,
    )
    page_size = 5_000

    def _rows():
        fetched = 0
        while fetched < limit:
            batch = _repo.list_assets(
                db, sort_by="gf_tag_count", sort_dir="desc",
                offset=fetched, limit=min(page_size, limit - fetched), **filters,
            )
            if not batch:
                break
            for row in batch:
                yield row
            fetched += len(batch)
            if len(batch) < page_size:
                break

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if fmt == "json":
        def _json_stream():
            yield "["
            first = True
            for row in _rows():
                payload = {k: row.get(k) for k in _EXPORT_COLUMNS}
                payload["gf_classified_at"] = (
                    payload["gf_classified_at"].isoformat()
                    if payload.get("gf_classified_at") else None
                )
                payload["program_id"] = str(payload["program_id"])
                payload["scope_id"] = str(payload["scope_id"])
                yield ("" if first else ",") + json.dumps(payload)
                first = False
            yield "]"

        return StreamingResponse(
            _json_stream(), media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="gf-assets-{stamp}.json"'},
        )

    def _csv_stream():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(_EXPORT_COLUMNS)
        yield buf.getvalue()
        for row in _rows():
            buf.seek(0)
            buf.truncate(0)
            writer.writerow([
                row.get("url"), row.get("host"), row.get("asset_type"),
                ",".join(row.get("gf_tags") or []),
                row.get("program_id"), row.get("scope_id"),
                row.get("gf_classified_at").isoformat()
                if row.get("gf_classified_at") else "",
            ])
            yield buf.getvalue()

    return StreamingResponse(
        _csv_stream(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="gf-assets-{stamp}.csv"'},
    )


@router.post("/scan-queue", response_model=GfScanQueueResponse,
             status_code=status.HTTP_202_ACCEPTED)
def queue_gf_assets_for_scan(
    payload: GfScanQueueRequest,
    db: Session = Depends(get_db),
) -> GfScanQueueResponse:
    """Queue selected assets for a follow-up scan (nuclei/dalfox/ghauri/custom).

    Active scanning is not implemented yet — this records the request and returns
    a queue id so the UI's bulk actions are wired end-to-end. When an
    active-scanning phase lands it consumes this queue.
    """
    if not payload.asset_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="asset_ids must not be empty",
        )
    queue_id = uuid.uuid4()
    _SCAN_QUEUE.append({
        "queue_id": queue_id,
        "tool": payload.tool,
        "asset_ids": [str(a) for a in payload.asset_ids],
        "notes": payload.notes,
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "status": "PENDING",
    })
    return GfScanQueueResponse(
        queued=len(payload.asset_ids),
        tool=payload.tool,
        queue_id=queue_id,
        status="PENDING",
        detail=(
            "Queued. Active scanning is not implemented yet — this request is "
            "recorded for the future scan-queue integration."
        ),
    )


@router.get("/scan-queue")
def list_gf_scan_queue() -> list[dict]:
    """Inspect what has been queued (most recent first)."""
    return list(reversed(_SCAN_QUEUE))


@router.get("/assets/{asset_id}", response_model=GfAssetResponse)
def get_gf_asset(
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> GfAssetResponse:
    """One GF-classified asset by id (URL or endpoint)."""
    row = _repo.get_asset(db, asset_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Asset {asset_id} not found",
        )
    return GfAssetResponse(**row)
