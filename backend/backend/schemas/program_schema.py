from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ProgramCreate(BaseModel):
    name: str
    platform: str | None = None
    description: str | None = None
    created_by: str | None = None
    status: str = "active"

    model_config = ConfigDict(
        extra="forbid",
    )


class ProgramUpdate(BaseModel):
    name: str | None = None
    platform: str | None = None
    description: str | None = None
    created_by: str | None = None
    status: str | None = None

    model_config = ConfigDict(
        extra="forbid",
    )


class ProgramResponse(BaseModel):
    id: UUID
    name: str
    platform: str | None = None
    status: str
    description: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
                "name": "Recon Project",
                "platform": "aws",
                "status": "active",
                "description": "External asset monitoring program",
                "created_by": "security-team@example.com",
                "created_at": "2026-06-07T00:00:00Z",
                "updated_at": "2026-06-07T00:00:00Z",
            }
        },
    )


class ProgramStatsResponse(BaseModel):
    program_id: UUID
    total_scopes: int
    active_scopes: int
    total_assets: int
    total_subdomains: int = 0
    total_hosts: int = 0
    live_hosts: int = 0
    total_dns_records: int = 0
    total_technologies: int = 0
    total_findings: int
    open_findings: int
    total_scan_runs: int
    total_notifications: int
    last_scan_at: datetime | None = None
    last_notification_at: datetime | None = None

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "program_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
                "total_scopes": 12,
                "active_scopes": 10,
                "total_assets": 482,
                "total_findings": 34,
                "open_findings": 12,
                "total_scan_runs": 27,
                "total_notifications": 5,
                "last_scan_at": "2026-06-07T12:34:56Z",
                "last_notification_at": "2026-06-07T12:45:10Z",
            }
        },
    )
