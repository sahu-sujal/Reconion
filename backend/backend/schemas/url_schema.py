from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class UrlResponse(BaseModel):
    id: UUID
    program_id: UUID
    scope_id: UUID
    host_id: UUID | None = None
    url: str
    normalized_url: str
    scheme: str | None = None
    host: str | None = None
    path: str | None = None
    query: str | None = None
    fragment: str | None = None
    extension: str | None = None
    directory: str | None = None
    filename: str | None = None
    depth: int = 0
    parameter_count: int = 0
    has_parameters: bool = False
    status: str | None = None
    source: str | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JsFileResponse(BaseModel):
    id: UUID
    program_id: UUID
    scope_id: UUID
    host_id: UUID | None = None
    url: str
    filename: str | None = None
    directory: str | None = None
    extension: str | None = None
    source: str | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedUrls(BaseModel):
    """Paginated URL listing with total count for the scope (matching filters)."""

    total: int
    offset: int
    limit: int
    items: list[UrlResponse]


class PaginatedJsFiles(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[JsFileResponse]
