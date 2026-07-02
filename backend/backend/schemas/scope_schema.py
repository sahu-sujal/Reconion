from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from database.models.enums import ScopeType


class ScopeCreate(BaseModel):
    program_id: UUID
    target: str
    scope_type: str = ScopeType.ROOT_DOMAIN.value
    priority: int = 50
    is_active: bool = True
    notes: str | None = None

    model_config = ConfigDict(
        extra="forbid",
    )


class ScopeUpdate(BaseModel):
    scope_type: str | None = None
    priority: int | None = None
    is_active: bool | None = None
    notes: str | None = None

    model_config = ConfigDict(
        extra="forbid",
    )


class ScopeResponse(BaseModel):
    id: UUID
    program_id: UUID
    target: str
    scope_type: str
    priority: int
    is_active: bool
    notes: str | None = None
    last_scan_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "e1f8b619-1841-4b72-9ebb-9a5b70b6ed5f",
                "program_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
                "target": "example.com",
                "scope_type": "ROOT_DOMAIN",
                "priority": 50,
                "is_active": True,
                "notes": "Primary scope for external assets",
                "last_scan_at": "2026-06-07T12:00:00Z",
                "created_at": "2026-06-07T00:00:00Z",
                "updated_at": "2026-06-07T00:00:00Z",
            }
        },
    )


class ScopeStatsResponse(BaseModel):
    scope_id: UUID
    assets_count: int
    findings_count: int
    notifications_sent: int
    urls_count: int = 0
    new_urls: int = 0
    js_count: int = 0
    new_js: int = 0
    endpoints_count: int = 0
    new_endpoints: int = 0
    secrets_count: int = 0
    new_secrets: int = 0
    last_scan_at: datetime | None = None
    last_notification_at: datetime | None = None

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "scope_id": "e1f8b619-1841-4b72-9ebb-9a5b70b6ed5f",
                "assets_count": 142,
                "findings_count": 18,
                "notifications_sent": 3,
                "last_scan_at": "2026-06-07T11:40:00Z",
                "last_notification_at": "2026-06-07T11:45:00Z",
            }
        },
    )
