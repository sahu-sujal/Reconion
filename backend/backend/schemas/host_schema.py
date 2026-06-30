from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class HostResponse(BaseModel):
    id: UUID
    asset_id: UUID
    program_id: UUID
    scope_id: UUID
    host: str
    ip: str | None = None
    scheme: str | None = None
    port: int | None = None
    status_code: int | None = None
    title: str | None = None
    content_length: int | None = None
    response_time: float | None = None
    cdn: bool = False
    waf: bool = False
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DnsRecordResponse(BaseModel):
    id: UUID
    program_id: UUID
    scope_id: UUID
    host_id: UUID
    subdomain_id: UUID | None = None
    subdomain: str | None = None
    record_type: str
    record_value: str
    ttl: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("subdomain", mode="before")
    @classmethod
    def _extract_subdomain_name(cls, value: object) -> str | None:
        # When built from an ORM object the `subdomain` field holds the
        # Subdomain relationship object; extract the string from it before
        # the field's str type validation runs.
        if value is None or isinstance(value, str):
            return value
        return getattr(value, "subdomain", None)


class HttpResponseResponse(BaseModel):
    id: UUID
    program_id: UUID
    scope_id: UUID
    host_id: UUID
    url: str
    status_code: int | None = None
    title: str | None = None
    content_length: int | None = None
    server: str | None = None
    technologies: list[str] | None = None
    response_time: float | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TechnologyResponse(BaseModel):
    id: UUID
    program_id: UUID
    scope_id: UUID
    host_id: UUID
    technology: str
    version: str | None = None
    confidence: int | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
