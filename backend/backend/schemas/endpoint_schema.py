from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EndpointResponse(BaseModel):
    """A single endpoint in the unified inventory (Phase 6.1)."""

    id: UUID
    program_id: UUID
    scope_id: UUID
    host_id: UUID | None = None
    js_file_id: UUID | None = None
    absolute_url: str
    normalized_url: str
    scheme: str | None = None
    host: str | None = None
    path: str | None = None
    query: str | None = None
    fragment: str | None = None
    discovery_tools: list[str] = []
    discovery_source: str
    source_js_file: str | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedEndpoints(BaseModel):
    """Paginated endpoint listing with total count for the current filters."""

    total: int
    offset: int
    limit: int
    items: list[EndpointResponse]


class EndpointStatsResponse(BaseModel):
    """Dashboard counters for the endpoint inventory."""

    total_endpoints: int
    new_endpoints: int
    endpoints_per_host: dict[str, int]
    endpoints_per_subdomain: dict[str, int]
