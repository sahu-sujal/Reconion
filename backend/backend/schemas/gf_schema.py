from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class GfCategoryResponse(BaseModel):
    """One GF category present in the data, with its asset counts."""
    category: str
    asset_count: int = 0
    url_count: int = 0
    endpoint_count: int = 0
    host_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class GfAssetResponse(BaseModel):
    """A GF-classified asset — a row from either urls or endpoints."""
    id: UUID
    asset_type: str                      # 'URL' | 'ENDPOINT'
    url: str
    host: str | None = None
    program_id: UUID
    scope_id: UUID
    host_id: UUID | None = None
    gf_tags: list[str] = []
    gf_tag_count: int = 0
    gf_classified_at: datetime | None = None
    asset_category: str | None = None
    mime_type: str | None = None
    status: str | None = None
    discovery_source: str | None = None
    parameter_count: int = 0
    extension: str | None = None
    is_api: bool = False
    first_seen: datetime | None = None
    last_seen: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PaginatedGfAssets(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[GfAssetResponse]


class GfCategoryCount(BaseModel):
    category: str
    asset_count: int


class GfHostCount(BaseModel):
    host: str | None = None
    asset_count: int


class GfProgramCount(BaseModel):
    program_id: UUID
    program_name: str | None = None
    asset_count: int


class GfScopeCount(BaseModel):
    scope_id: UUID
    scope_target: str | None = None
    asset_count: int


class GfRecentAsset(BaseModel):
    id: UUID
    host: str | None = None
    gf_tags: list[str] = []
    gf_classified_at: datetime | None = None


class GfStatisticsResponse(BaseModel):
    """Dashboard aggregates for the GF Intelligence landing page."""
    total_assets: int = 0
    classified_assets: int = 0
    assets_with_matches: int = 0
    assets_without_matches: int = 0
    unique_categories: int = 0
    top_categories: list[GfCategoryCount] = []
    assets_per_host: list[GfHostCount] = []
    assets_per_program: list[GfProgramCount] = []
    assets_per_scope: list[GfScopeCount] = []
    recently_classified: list[GfRecentAsset] = []


class GfScanQueueRequest(BaseModel):
    """Queue selected assets for a follow-up scan.

    ``tool`` is free-form (nuclei, dalfox, ghauri, custom) so new scanners can be
    queued without an API change; the queue is the integration point for a future
    active-scanning phase.
    """
    asset_ids: list[UUID]
    tool: str
    notes: str | None = None


class GfScanQueueResponse(BaseModel):
    queued: int
    tool: str
    queue_id: UUID | None = None
    status: str = "PENDING"
    detail: str | None = None
