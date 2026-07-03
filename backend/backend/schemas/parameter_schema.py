"""Parameter Inventory schemas — Phase 6.4."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ParameterResponse(BaseModel):
    """One discovered parameter, linked to its originating URL / Endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    program_id: UUID
    scope_id: UUID
    host_id: UUID | None = None
    asset_id: UUID
    asset_type: str
    asset_url: str
    host: str | None = None
    parameter_name: str
    parameter_type: str
    parameter_source: str
    discovery_tools: list[str] = []
    first_seen: datetime | None = None
    last_seen: datetime | None = None


class PaginatedParameters(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[ParameterResponse]


class ParameterTypeMetaResponse(BaseModel):
    type: str
    label: str
    interesting: bool


class CommonParameter(BaseModel):
    name: str
    count: int


class ParameterStatsResponse(BaseModel):
    """Dashboard counters for the parameter inventory."""

    total_parameters: int
    unique_parameters: int
    new_parameters: int
    by_type: dict[str, int]
    by_tool: dict[str, int]
    most_common: list[CommonParameter]
    types: list[ParameterTypeMetaResponse]
