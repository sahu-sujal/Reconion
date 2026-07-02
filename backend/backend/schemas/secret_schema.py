from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SecretResponse(BaseModel):
    """A single secret in the inventory (Phase 6.2). Value is unmasked."""

    id: UUID
    program_id: UUID
    scope_id: UUID
    host_id: UUID | None = None
    js_file_id: UUID | None = None
    js_file_url: str | None = None
    host: str | None = None
    secret_type: str
    secret_value: str
    normalized_secret: str
    fingerprint: str
    confidence: int
    severity: str
    discovery_tools: list[str] = []
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedSecrets(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[SecretResponse]


class SecretStatsResponse(BaseModel):
    """Dashboard counters for the secret inventory."""

    total_secrets: int
    critical_secrets: int
    high_secrets: int
    aws_keys: int
    github_tokens: int
    jwt_tokens: int
    private_keys: int
    database_credentials: int
    slack_tokens: int
    google_api_keys: int
    by_severity: dict[str, int]
    by_type: dict[str, int]
