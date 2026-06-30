from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, computed_field


class ScanStartRequest(BaseModel):
    program_id: UUID
    scope_id: UUID
    scan_type: str = "SUBDOMAIN"

    model_config = ConfigDict(extra="forbid")


class ScanRunResponse(BaseModel):
    id: UUID
    program_id: UUID
    scope_id: UUID
    target: str | None = None
    scan_type: str
    worker_name: str
    status: str
    # Legacy aggregate (equals unique_count for new scans)
    records_found: int
    # Subdomain pipeline metrics
    subfinder_count: int = 0
    assetfinder_count: int = 0
    merged_count: int = 0
    unique_count: int = 0
    new_count: int = 0
    existing_count: int = 0
    # DNS scan metrics
    dnsx_count: int = 0
    resolved_count: int = 0
    new_hosts_count: int = 0
    # HTTP scan metrics
    httpx_count: int = 0
    live_count: int = 0
    new_live_count: int = 0
    error_message: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ToolExecutionSummary(BaseModel):
    id: UUID
    tool_name: str
    status: str
    raw_records_found: int = 0
    records_found: int = 0
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


class ScanReportResponse(BaseModel):
    id: UUID
    program_id: UUID
    scope_id: UUID
    target: str | None = None
    scan_type: str
    status: str
    # Subdomain pipeline counters
    subfinder_count: int = 0
    assetfinder_count: int = 0
    merged_count: int = 0
    unique_count: int = 0
    new_count: int = 0
    existing_count: int = 0
    # DNS scan counters
    dnsx_count: int = 0
    resolved_count: int = 0
    new_hosts_count: int = 0
    # HTTP scan counters
    httpx_count: int = 0
    live_count: int = 0
    new_live_count: int = 0
    # Content discovery counters
    gau_count: int = 0
    waybackurls_count: int = 0
    katana_count: int = 0
    hakrawler_count: int = 0
    total_urls_count: int = 0
    new_urls_count: int = 0
    total_js_count: int = 0
    new_js_count: int = 0
    records_found: int = 0
    error_message: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    tools: list[ToolExecutionSummary] = []

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None

    @computed_field
    @property
    def summary(self) -> str:
        if not self.tools:
            return "No tools ran."
        parts: list[str] = []
        for t in self.tools:
            if t.status == "COMPLETED":
                parts.append(
                    f"{t.tool_name}: {t.raw_records_found} raw → {t.records_found} in-scope"
                )
            elif t.status == "FAILED":
                reason = t.error_message or "unknown error"
                parts.append(f"{t.tool_name}: FAILED ({reason})")
            else:
                parts.append(f"{t.tool_name}: {t.status.lower()}")
        return " | ".join(parts)
