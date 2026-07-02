"""Secret inventory API (Phase 6.2).

    GET /programs/{program_id}/secrets
    GET /scopes/{scope_id}/secrets
    GET /subdomains/{subdomain_id}/secrets
    GET /hosts/{host_id}/secrets
    GET /js-files/{js_file_id}/secrets
    GET /scopes/{scope_id}/secret-stats     dashboard counters
    GET /programs/{program_id}/secret-stats

All listing endpoints support search / pagination / sorting / filtering.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.schemas.secret_schema import PaginatedSecrets, SecretStatsResponse
from database.models.enums import SecretType
from repositories.host_repository import HostRepository
from repositories.js_file_repository import JsFileRepository
from repositories.js_secret_repository import JsSecretRepository
from repositories.subdomain_repository import SubdomainRepository

router = APIRouter(tags=["Secrets"])

_secret_repo = JsSecretRepository()
_subdomain_repo = SubdomainRepository()
_host_repo = HostRepository()
_js_repo = JsFileRepository()


def _list_params(
    offset: int, limit: int, search, host, secret_type, severity, tool, js_url, sort_by, sort_dir,
) -> dict:
    return dict(
        offset=offset, limit=limit, search=search, host=host, secret_type=secret_type,
        severity=severity, tool=tool, js_url=js_url, sort_by=sort_by, sort_dir=sort_dir,
    )


_COMMON_QUERY = dict(
    offset=Query(0, ge=0),
    limit=Query(100, ge=1, le=10000),
    search=Query(None, description="Match on value, type, host, or JS URL"),
    host=Query(None, description="Host filter (domain + subdomains)"),
    secret_type=Query(None, description="Filter by secret type (AWS_ACCESS_KEY…)"),
    severity=Query(None, description="Filter by severity (CRITICAL/HIGH/…)"),
    tool=Query(None, description="Filter by discovery tool (SECRETFINDER/MANTRA/NUCLEI_EXPOSURES)"),
    js_url=Query(None, description="Filter by originating JS file URL"),
    sort_by=Query("severity", description="Column to sort by"),
    sort_dir=Query("asc", description="asc or desc"),
)


@router.get("/programs/{program_id}/secrets", response_model=PaginatedSecrets)
def get_program_secrets(
    program_id: uuid.UUID,
    offset: int = _COMMON_QUERY["offset"], limit: int = _COMMON_QUERY["limit"],
    search: str | None = _COMMON_QUERY["search"], host: str | None = _COMMON_QUERY["host"],
    secret_type: str | None = _COMMON_QUERY["secret_type"], severity: str | None = _COMMON_QUERY["severity"],
    tool: str | None = _COMMON_QUERY["tool"], js_url: str | None = _COMMON_QUERY["js_url"],
    sort_by: str = _COMMON_QUERY["sort_by"], sort_dir: str = _COMMON_QUERY["sort_dir"],
    db: Session = Depends(get_db),
) -> PaginatedSecrets:
    params = _list_params(offset, limit, search, host, secret_type, severity, tool, js_url, sort_by, sort_dir)
    items = _secret_repo.list_secrets(db, program_id=program_id, **params)
    total = _secret_repo.count_secrets(
        db, program_id=program_id, search=search, host=host, secret_type=secret_type,
        severity=severity, tool=tool, js_url=js_url,
    )
    return PaginatedSecrets(total=total, offset=offset, limit=limit, items=items)


@router.get("/scopes/{scope_id}/secrets", response_model=PaginatedSecrets)
def get_scope_secrets(
    scope_id: uuid.UUID,
    offset: int = _COMMON_QUERY["offset"], limit: int = _COMMON_QUERY["limit"],
    search: str | None = _COMMON_QUERY["search"], host: str | None = _COMMON_QUERY["host"],
    secret_type: str | None = _COMMON_QUERY["secret_type"], severity: str | None = _COMMON_QUERY["severity"],
    tool: str | None = _COMMON_QUERY["tool"], js_url: str | None = _COMMON_QUERY["js_url"],
    sort_by: str = _COMMON_QUERY["sort_by"], sort_dir: str = _COMMON_QUERY["sort_dir"],
    db: Session = Depends(get_db),
) -> PaginatedSecrets:
    params = _list_params(offset, limit, search, host, secret_type, severity, tool, js_url, sort_by, sort_dir)
    items = _secret_repo.list_secrets(db, scope_id=scope_id, **params)
    total = _secret_repo.count_secrets(
        db, scope_id=scope_id, search=search, host=host, secret_type=secret_type,
        severity=severity, tool=tool, js_url=js_url,
    )
    return PaginatedSecrets(total=total, offset=offset, limit=limit, items=items)


@router.get("/subdomains/{subdomain_id}/secrets", response_model=PaginatedSecrets)
def get_subdomain_secrets(
    subdomain_id: uuid.UUID,
    offset: int = _COMMON_QUERY["offset"], limit: int = _COMMON_QUERY["limit"],
    search: str | None = _COMMON_QUERY["search"],
    secret_type: str | None = _COMMON_QUERY["secret_type"], severity: str | None = _COMMON_QUERY["severity"],
    tool: str | None = _COMMON_QUERY["tool"], js_url: str | None = _COMMON_QUERY["js_url"],
    sort_by: str = _COMMON_QUERY["sort_by"], sort_dir: str = _COMMON_QUERY["sort_dir"],
    db: Session = Depends(get_db),
) -> PaginatedSecrets:
    sub = _subdomain_repo.get(db, subdomain_id)
    if sub is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subdomain not found")
    items = _secret_repo.list_secrets(
        db, scope_id=sub.scope_id, host_value=sub.subdomain, offset=offset, limit=limit,
        search=search, secret_type=secret_type, severity=severity, tool=tool, js_url=js_url,
        sort_by=sort_by, sort_dir=sort_dir,
    )
    total = _secret_repo.count_secrets(
        db, scope_id=sub.scope_id, host_value=sub.subdomain, search=search,
        secret_type=secret_type, severity=severity, tool=tool, js_url=js_url,
    )
    return PaginatedSecrets(total=total, offset=offset, limit=limit, items=items)


@router.get("/hosts/{host_id}/secrets", response_model=PaginatedSecrets)
def get_host_secrets(
    host_id: uuid.UUID,
    offset: int = _COMMON_QUERY["offset"], limit: int = _COMMON_QUERY["limit"],
    search: str | None = _COMMON_QUERY["search"],
    secret_type: str | None = _COMMON_QUERY["secret_type"], severity: str | None = _COMMON_QUERY["severity"],
    tool: str | None = _COMMON_QUERY["tool"], js_url: str | None = _COMMON_QUERY["js_url"],
    sort_by: str = _COMMON_QUERY["sort_by"], sort_dir: str = _COMMON_QUERY["sort_dir"],
    db: Session = Depends(get_db),
) -> PaginatedSecrets:
    items = _secret_repo.list_secrets(
        db, host_id=host_id, offset=offset, limit=limit, search=search,
        secret_type=secret_type, severity=severity, tool=tool, js_url=js_url,
        sort_by=sort_by, sort_dir=sort_dir,
    )
    total = _secret_repo.count_secrets(
        db, host_id=host_id, search=search, secret_type=secret_type,
        severity=severity, tool=tool, js_url=js_url,
    )
    return PaginatedSecrets(total=total, offset=offset, limit=limit, items=items)


@router.get("/js-files/{js_file_id}/secrets", response_model=PaginatedSecrets)
def get_js_file_secrets(
    js_file_id: uuid.UUID,
    offset: int = _COMMON_QUERY["offset"], limit: int = _COMMON_QUERY["limit"],
    search: str | None = _COMMON_QUERY["search"],
    secret_type: str | None = _COMMON_QUERY["secret_type"], severity: str | None = _COMMON_QUERY["severity"],
    tool: str | None = _COMMON_QUERY["tool"],
    sort_by: str = _COMMON_QUERY["sort_by"], sort_dir: str = _COMMON_QUERY["sort_dir"],
    db: Session = Depends(get_db),
) -> PaginatedSecrets:
    js = _js_repo.get(db, js_file_id)
    if js is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="JS file not found")
    # Match by js_file_id when set, else by the JS URL (worker may leave the FK null).
    items = _secret_repo.list_secrets(
        db, scope_id=js.scope_id, js_url=js.url, offset=offset, limit=limit,
        search=search, secret_type=secret_type, severity=severity, tool=tool,
        sort_by=sort_by, sort_dir=sort_dir,
    )
    total = _secret_repo.count_secrets(
        db, scope_id=js.scope_id, js_url=js.url, search=search,
        secret_type=secret_type, severity=severity, tool=tool,
    )
    return PaginatedSecrets(total=total, offset=offset, limit=limit, items=items)


# ------------------------------------------------------------------
# Dashboard stats
# ------------------------------------------------------------------

def _stats_response(raw: dict) -> SecretStatsResponse:
    by_sev = raw["by_severity"]
    by_type = raw["by_type"]
    return SecretStatsResponse(
        total_secrets=raw["total"],
        critical_secrets=by_sev.get("CRITICAL", 0),
        high_secrets=by_sev.get("HIGH", 0),
        aws_keys=(by_type.get(SecretType.AWS_ACCESS_KEY.value, 0)
                  + by_type.get(SecretType.AWS_SECRET_KEY.value, 0)
                  + by_type.get(SecretType.AWS_SESSION_TOKEN.value, 0)),
        github_tokens=by_type.get(SecretType.GITHUB_TOKEN.value, 0),
        jwt_tokens=by_type.get(SecretType.JWT.value, 0),
        private_keys=(by_type.get(SecretType.PRIVATE_KEY.value, 0)
                      + by_type.get(SecretType.RSA_PRIVATE_KEY.value, 0)
                      + by_type.get(SecretType.OPENSSH_PRIVATE_KEY.value, 0)
                      + by_type.get(SecretType.SSH_PRIVATE_KEY.value, 0)),
        database_credentials=(by_type.get(SecretType.DATABASE_URL.value, 0)
                              + by_type.get(SecretType.MYSQL_URI.value, 0)
                              + by_type.get(SecretType.POSTGRES_URI.value, 0)
                              + by_type.get(SecretType.MONGODB_URI.value, 0)
                              + by_type.get(SecretType.REDIS_URI.value, 0)
                              + by_type.get(SecretType.ELASTICSEARCH_URI.value, 0)),
        slack_tokens=by_type.get(SecretType.SLACK_TOKEN.value, 0),
        google_api_keys=by_type.get(SecretType.GOOGLE_API_KEY.value, 0),
        by_severity=by_sev,
        by_type=by_type,
    )


@router.get("/scopes/{scope_id}/secret-stats", response_model=SecretStatsResponse)
def get_scope_secret_stats(scope_id: uuid.UUID, db: Session = Depends(get_db)) -> SecretStatsResponse:
    return _stats_response(_secret_repo.stats(db, scope_id=scope_id))


@router.get("/programs/{program_id}/secret-stats", response_model=SecretStatsResponse)
def get_program_secret_stats(program_id: uuid.UUID, db: Session = Depends(get_db)) -> SecretStatsResponse:
    return _stats_response(_secret_repo.stats(db, program_id=program_id))
