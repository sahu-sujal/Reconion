"""Parameter Inventory API (Phase 6.4).

    GET /programs/{program_id}/parameters
    GET /scopes/{scope_id}/parameters
    GET /hosts/{host_id}/parameters
    GET /assets/{asset_id}/parameters        (asset = a url or endpoint row)
    GET /scopes/{scope_id}/parameter-stats   dashboard counters
    GET /programs/{program_id}/parameter-stats
    GET /parameter-types                      taxonomy metadata (legend order)

All listing endpoints support search / pagination / sorting / filtering by host,
discovery tool, and parameter type.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.schemas.parameter_schema import (
    PaginatedParameters,
    ParameterStatsResponse,
    ParameterTypeMetaResponse,
)
from repositories.parameter_repository import ParameterRepository
from tools.common.parameter_utils import all_parameter_types

router = APIRouter(tags=["Parameters"])

_param_repo = ParameterRepository()

_COMMON_QUERY = dict(
    offset=Query(0, ge=0),
    limit=Query(100, ge=1, le=10000),
    search=Query(None, description="Match on parameter name, asset URL, or host"),
    host=Query(None, description="Host filter (domain + subdomains)"),
    tool=Query(None, description="Filter by discovery tool (ARJUN/PARAMSPIDER)"),
    parameter_type=Query(None, description="Filter by parameter type (IDENTIFIER, REDIRECT…)"),
    asset_type=Query(None, description="Filter by asset type (URL / ENDPOINT)"),
    sort_by=Query("parameter_name", description="Column to sort by"),
    sort_dir=Query("asc", description="asc or desc"),
)


def _list_params(offset, limit, search, host, tool, parameter_type, asset_type, sort_by, sort_dir) -> dict:
    return dict(
        offset=offset, limit=limit, search=search, host=host, tool=tool,
        parameter_type=parameter_type, asset_type=asset_type,
        sort_by=sort_by, sort_dir=sort_dir,
    )


@router.get("/programs/{program_id}/parameters", response_model=PaginatedParameters)
def get_program_parameters(
    program_id: uuid.UUID,
    offset: int = _COMMON_QUERY["offset"], limit: int = _COMMON_QUERY["limit"],
    search: str | None = _COMMON_QUERY["search"], host: str | None = _COMMON_QUERY["host"],
    tool: str | None = _COMMON_QUERY["tool"], parameter_type: str | None = _COMMON_QUERY["parameter_type"],
    asset_type: str | None = _COMMON_QUERY["asset_type"],
    sort_by: str = _COMMON_QUERY["sort_by"], sort_dir: str = _COMMON_QUERY["sort_dir"],
    db: Session = Depends(get_db),
) -> PaginatedParameters:
    params = _list_params(offset, limit, search, host, tool, parameter_type, asset_type, sort_by, sort_dir)
    items = _param_repo.list_parameters(db, program_id=program_id, **params)
    total = _param_repo.count_parameters(
        db, program_id=program_id, search=search, host=host, tool=tool,
        parameter_type=parameter_type, asset_type=asset_type,
    )
    return PaginatedParameters(total=total, offset=offset, limit=limit, items=items)


@router.get("/scopes/{scope_id}/parameters", response_model=PaginatedParameters)
def get_scope_parameters(
    scope_id: uuid.UUID,
    offset: int = _COMMON_QUERY["offset"], limit: int = _COMMON_QUERY["limit"],
    search: str | None = _COMMON_QUERY["search"], host: str | None = _COMMON_QUERY["host"],
    tool: str | None = _COMMON_QUERY["tool"], parameter_type: str | None = _COMMON_QUERY["parameter_type"],
    asset_type: str | None = _COMMON_QUERY["asset_type"],
    sort_by: str = _COMMON_QUERY["sort_by"], sort_dir: str = _COMMON_QUERY["sort_dir"],
    db: Session = Depends(get_db),
) -> PaginatedParameters:
    params = _list_params(offset, limit, search, host, tool, parameter_type, asset_type, sort_by, sort_dir)
    items = _param_repo.list_parameters(db, scope_id=scope_id, **params)
    total = _param_repo.count_parameters(
        db, scope_id=scope_id, search=search, host=host, tool=tool,
        parameter_type=parameter_type, asset_type=asset_type,
    )
    return PaginatedParameters(total=total, offset=offset, limit=limit, items=items)


@router.get("/hosts/{host_id}/parameters", response_model=PaginatedParameters)
def get_host_parameters(
    host_id: uuid.UUID,
    offset: int = _COMMON_QUERY["offset"], limit: int = _COMMON_QUERY["limit"],
    search: str | None = _COMMON_QUERY["search"],
    tool: str | None = _COMMON_QUERY["tool"], parameter_type: str | None = _COMMON_QUERY["parameter_type"],
    asset_type: str | None = _COMMON_QUERY["asset_type"],
    sort_by: str = _COMMON_QUERY["sort_by"], sort_dir: str = _COMMON_QUERY["sort_dir"],
    db: Session = Depends(get_db),
) -> PaginatedParameters:
    items = _param_repo.list_parameters(
        db, host_id=host_id, offset=offset, limit=limit, search=search, tool=tool,
        parameter_type=parameter_type, asset_type=asset_type, sort_by=sort_by, sort_dir=sort_dir,
    )
    total = _param_repo.count_parameters(
        db, host_id=host_id, search=search, tool=tool,
        parameter_type=parameter_type, asset_type=asset_type,
    )
    return PaginatedParameters(total=total, offset=offset, limit=limit, items=items)


@router.get("/assets/{asset_id}/parameters", response_model=PaginatedParameters)
def get_asset_parameters(
    asset_id: uuid.UUID,
    offset: int = _COMMON_QUERY["offset"], limit: int = _COMMON_QUERY["limit"],
    search: str | None = _COMMON_QUERY["search"],
    tool: str | None = _COMMON_QUERY["tool"], parameter_type: str | None = _COMMON_QUERY["parameter_type"],
    sort_by: str = _COMMON_QUERY["sort_by"], sort_dir: str = _COMMON_QUERY["sort_dir"],
    db: Session = Depends(get_db),
) -> PaginatedParameters:
    """Parameters discovered on one asset (a url or endpoint row) — Explorer drill-down."""
    items = _param_repo.list_parameters(
        db, asset_id=asset_id, offset=offset, limit=limit, search=search, tool=tool,
        parameter_type=parameter_type, sort_by=sort_by, sort_dir=sort_dir,
    )
    total = _param_repo.count_parameters(
        db, asset_id=asset_id, search=search, tool=tool, parameter_type=parameter_type,
    )
    return PaginatedParameters(total=total, offset=offset, limit=limit, items=items)


# ------------------------------------------------------------------
# Taxonomy + dashboard stats
# ------------------------------------------------------------------

@router.get("/parameter-types", response_model=list[ParameterTypeMetaResponse])
def get_parameter_types() -> list[ParameterTypeMetaResponse]:
    """The parameter-type taxonomy (stable order) — drives the Explorer legend."""
    return [ParameterTypeMetaResponse(**t) for t in all_parameter_types()]


def _stats_response(db: Session, *, program_id=None, scope_id=None) -> ParameterStatsResponse:
    raw = _param_repo.stats(db, program_id=program_id, scope_id=scope_id)
    by_tool = _param_repo.tool_counts(db, program_id=program_id, scope_id=scope_id)
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    new_count = (
        _param_repo.new_parameters_since(db, scope_id, since) if scope_id is not None else 0
    )
    return ParameterStatsResponse(
        total_parameters=raw["total"],
        unique_parameters=raw["unique_parameters"],
        new_parameters=new_count,
        by_type=raw["by_type"],
        by_tool=by_tool,
        most_common=raw["most_common"],
        types=[ParameterTypeMetaResponse(**t) for t in all_parameter_types()],
    )


@router.get("/scopes/{scope_id}/parameter-stats", response_model=ParameterStatsResponse)
def get_scope_parameter_stats(scope_id: uuid.UUID, db: Session = Depends(get_db)) -> ParameterStatsResponse:
    return _stats_response(db, scope_id=scope_id)


@router.get("/programs/{program_id}/parameter-stats", response_model=ParameterStatsResponse)
def get_program_parameter_stats(program_id: uuid.UUID, db: Session = Depends(get_db)) -> ParameterStatsResponse:
    return _stats_response(db, program_id=program_id)
