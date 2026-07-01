from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SubdomainResponse(BaseModel):
    id: UUID
    subdomain: str
    source: str | None = None
    endpoint_count: int = 0
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    scope_id: UUID
    program_id: UUID
    asset_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "a1b2c3d4-e5f6-7890-ab12-cd34ef567890",
                "subdomain": "api.detectify.com",
                "source": "assetfinder,subfinder",
                "first_seen": "2026-06-07T12:00:00Z",
                "last_seen": "2026-06-07T12:05:00Z",
                "scope_id": "e1f8b619-1841-4b72-9ebb-9a5b70b6ed5f",
                "program_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
                "asset_id": "f1e2d3c4-b5a6-7890-cd12-ef34ab567890",
                "created_at": "2026-06-07T12:00:00Z",
                "updated_at": "2026-06-07T12:05:00Z",
            }
        },
    )
