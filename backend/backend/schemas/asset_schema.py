"""Asset Explorer schemas — Phase 6.3."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AssetResponse(BaseModel):
    """One classified asset from the unified ``asset_inventory`` view.

    ``source_kind`` records which table it came from (URL / ENDPOINT / JS) so the
    Explorer can render the right per-category detail. Category-specific
    enrichment (size, endpoints_extracted, secrets_found) is filled in for the JS
    category only and left null elsewhere.
    """

    id: UUID
    source_kind: str
    program_id: UUID
    scope_id: UUID
    host: str | None = None
    normalized_url: str
    asset_category: str | None = None
    extension: str | None = None
    mime_type: str | None = None
    has_parameters: bool = False
    parameter_count: int = 0
    is_static: bool = False
    is_dynamic: bool = False
    is_api: bool = False
    is_document: bool = False
    is_script: bool = False
    is_archive: bool = False
    is_configuration: bool = False
    is_backup: bool = False
    discovery_source: str | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None

    # JS-category enrichment (null for other categories).
    size_bytes: int | None = None
    endpoints_extracted: int | None = None
    secrets_found: int | None = None


class PaginatedAssets(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[AssetResponse]


class CategoryMetaResponse(BaseModel):
    category: str
    label: str
    group: str
    traits: list[str]
    sensitive: bool


class AssetStatsResponse(BaseModel):
    """Dashboard + sidebar asset statistics."""

    total_assets: int
    by_category: dict[str, int]
    categories: list[CategoryMetaResponse]
