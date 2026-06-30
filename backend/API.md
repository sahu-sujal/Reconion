# Recon Platform — API Reference

Complete request/response structure for every endpoint, organized by module
(router). This document is generated from the source in `backend/api/*` and
`backend/schemas/*`; see [README.md](README.md) for architecture and workflow.

- **Base URL:** `http://localhost:8000`
- **Interactive docs:** `/docs` (Swagger UI) · `/redoc` · `/openapi.json`
- **Content type:** `application/json` for all request bodies and responses
- **IDs:** UUID v4 · **Timestamps:** UTC, ISO-8601 (`2026-06-07T12:00:00Z`)

### Modules

| Module (router)                    | Prefix      | Tag       |
| ---------------------------------- | ----------- | --------- |
| [Health](#1-health-module)         | —           | Health    |
| [Stats](#15-stats-module)          | `/stats`    | Stats     |
| [Programs](#2-programs-module)     | `/programs` | Programs  |
| [Scopes](#3-scopes-module)         | `/scopes`   | Scopes    |
| [Scans](#4-scans-module)           | `/scans`    | Scans     |

### Conventions

- Create/Update bodies use Pydantic `extra="forbid"` — **unknown fields → 422**.
- Error responses are always `{"detail": "<message>"}`.
- Optional fields may be `null`; create requests may omit them (defaults apply).

| Status | Meaning                                                        |
| ------ | ------------------------------------------------------------- |
| 200    | OK                                                            |
| 201    | Created                                                       |
| 202    | Accepted (scan queued — async)                                |
| 204    | No Content (delete)                                           |
| 400    | Bad request (`ValueError` / `APIError`)                       |
| 404    | Not found (`EntityNotFoundError`)                             |
| 409    | Conflict (scope already scanning / deleting an active scan)   |
| 422    | Validation error (FastAPI/Pydantic)                           |
| 500    | Internal server error                                         |

---

## 1. Health module

`backend/api/health_routes.py`

### `GET /health`

Health check. No parameters.

**Response 200**
```json
{ "status": "ok", "service": "recon-platform" }
```

---

## 1.5. Stats module

`backend/api/stats_routes.py` · prefix `/stats` · schemas in `stats_schema.py`

### `GET /stats` → 200 `GlobalStatsResponse`

Aggregate dashboard counts across all programs and scans. No parameters.

**Response 200**
```json
{
  "total_programs": 12,
  "active_programs": 9,
  "inactive_programs": 3,
  "running_scans": 2,
  "pending_scans": 1
}
```

| Field               | Type | Notes                                         |
| ------------------- | ---- | --------------------------------------------- |
| `total_programs`    | int  | non-deleted programs                          |
| `active_programs`   | int  | programs with `status = active`               |
| `inactive_programs` | int  | non-active (paused + archived)                |
| `running_scans`     | int  | scan runs in `RUNNING` state                  |
| `pending_scans`     | int  | scan runs in `PENDING` state                  |

---

## 2. Programs module

`backend/api/program_routes.py` · prefix `/programs` · schemas in `program_schema.py`

### Schemas

**`ProgramCreate`** (request)

| Field         | Type   | Required | Default    | Notes                |
| ------------- | ------ | -------- | ---------- | -------------------- |
| `name`        | string | yes      | —          |                      |
| `platform`    | string | no       | `null`     | e.g. hackerone       |
| `description` | string | no       | `null`     |                      |
| `created_by`  | string | no       | `null`     | owner                |
| `status`      | string | no       | `"active"` | active/paused/archived |

**`ProgramUpdate`** (request) — all fields optional (same set as create).

**`ProgramResponse`**

| Field | Type | | Field | Type |
| ----- | ---- |-| ----- | ---- |
| `id` | UUID | | `description` | string\|null |
| `name` | string | | `created_by` | string\|null |
| `platform` | string\|null | | `created_at` | datetime |
| `status` | string | | `updated_at` | datetime |

---

### `POST /programs` → 201 `ProgramResponse`

Create a new program.

**Request**
```json
{
  "name": "Recon Project",
  "platform": "aws",
  "description": "External asset monitoring program",
  "created_by": "security-team@example.com",
  "status": "active"
}
```
**Response 201**
```json
{
  "id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "name": "Recon Project",
  "platform": "aws",
  "status": "active",
  "description": "External asset monitoring program",
  "created_by": "security-team@example.com",
  "created_at": "2026-06-07T00:00:00Z",
  "updated_at": "2026-06-07T00:00:00Z"
}
```

### `GET /programs` → 200 `[ProgramResponse]`

List all programs. No parameters. Returns an array of `ProgramResponse`.

### `GET /programs/{program_id}` → 200 `ProgramResponse` · 404

Get one program by ID.

### `PATCH /programs/{program_id}` → 200 `ProgramResponse` · 404

Update program metadata. Body = `ProgramUpdate` (send only changed fields).

**Request**
```json
{ "status": "paused", "description": "Temporarily on hold" }
```

### `GET /programs/{program_id}/scopes` → 200 `[ScopeResponse]` · 404

List scopes belonging to a program.

| Query    | Type | Default | Constraints |
| -------- | ---- | ------- | ----------- |
| `offset` | int  | 0       | ≥ 0         |
| `limit`  | int  | 100     | 1–250       |

Response: array of [`ScopeResponse`](#scopes-schemas).

### `GET /programs/{program_id}/stats` → 200 `ProgramStatsResponse` · 404

Aggregate statistics for a program.

**Response 200**
```json
{
  "program_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "total_scopes": 12,
  "active_scopes": 10,
  "total_assets": 482,
  "total_subdomains": 1423,
  "total_hosts": 318,
  "live_hosts": 142,
  "total_dns_records": 901,
  "total_technologies": 64,
  "total_findings": 34,
  "open_findings": 12,
  "total_scan_runs": 27,
  "total_notifications": 5,
  "last_scan_at": "2026-06-07T12:34:56Z",
  "last_notification_at": "2026-06-07T12:45:10Z"
}
```

| Field | Type | | Field | Type |
| ----- | ---- |-| ----- | ---- |
| `program_id` | UUID | | `total_dns_records` | int |
| `total_scopes` | int | | `total_technologies` | int |
| `active_scopes` | int | | `total_findings` | int |
| `total_assets` | int | | `open_findings` | int |
| `total_subdomains` | int | | `total_scan_runs` | int |
| `total_hosts` | int | | `total_notifications` | int |
| `live_hosts` | int | | `last_scan_at` | datetime\|null |
| | | | `last_notification_at` | datetime\|null |

### `DELETE /programs/{program_id}` → 204 · 404

Delete a program. No response body.

---

## 3. Scopes module

`backend/api/scope_routes.py` · prefix `/scopes` · schemas in `scope_schema.py`, `subdomain_schema.py`, `host_schema.py`

<a id="scopes-schemas"></a>
### Schemas

**`ScopeCreate`** (request)

| Field        | Type   | Required | Default        | Notes                                   |
| ------------ | ------ | -------- | -------------- | --------------------------------------- |
| `program_id` | UUID   | yes      | —              | parent program                          |
| `target`     | string | yes      | —              | e.g. `example.com`                      |
| `scope_type` | string | no       | `ROOT_DOMAIN`  | enum (see below)                        |
| `priority`   | int    | no       | 50             |                                         |
| `is_active`  | bool   | no       | `true`         |                                         |
| `notes`      | string | no       | `null`         |                                         |

`scope_type` ∈ `ROOT_DOMAIN, WILDCARD_DOMAIN, SUBDOMAIN, URL, CIDR, IP_RANGE`

**`ScopeUpdate`** (request) — optional: `scope_type, priority, is_active, notes`
(target is **not** updatable).

**`ScopeResponse`**

| Field | Type | | Field | Type |
| ----- | ---- |-| ----- | ---- |
| `id` | UUID | | `is_active` | bool |
| `program_id` | UUID | | `notes` | string\|null |
| `target` | string | | `last_scan_at` | datetime\|null |
| `scope_type` | string | | `created_at` | datetime |
| `priority` | int | | `updated_at` | datetime |

---

### `POST /scopes` → 201 `ScopeResponse` · 400 · 404

Create a scope for a program. `404` if the program doesn't exist; `400` on
invalid input.

**Request**
```json
{
  "program_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "target": "example.com",
  "scope_type": "ROOT_DOMAIN",
  "priority": 50,
  "is_active": true,
  "notes": "Primary scope for external assets"
}
```
**Response 201**
```json
{
  "id": "e1f8b619-1841-4b72-9ebb-9a5b70b6ed5f",
  "program_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "target": "example.com",
  "scope_type": "ROOT_DOMAIN",
  "priority": 50,
  "is_active": true,
  "notes": "Primary scope for external assets",
  "last_scan_at": null,
  "created_at": "2026-06-07T00:00:00Z",
  "updated_at": "2026-06-07T00:00:00Z"
}
```

### `GET /scopes` → 200 `[ScopeResponse]`

List scopes, optionally filtered.

| Query        | Type | Default | Notes                  |
| ------------ | ---- | ------- | ---------------------- |
| `program_id` | UUID | —       | optional program filter |

### `GET /scopes/{scope_id}` → 200 `ScopeResponse` · 404

### `PATCH /scopes/{scope_id}` → 200 `ScopeResponse` · 400 · 404

Body = `ScopeUpdate`.
```json
{ "priority": 80, "is_active": false }
```

### `GET /scopes/{scope_id}/stats` → 200 `ScopeStatsResponse` · 404

```json
{
  "scope_id": "e1f8b619-1841-4b72-9ebb-9a5b70b6ed5f",
  "assets_count": 142,
  "findings_count": 18,
  "notifications_sent": 3,
  "last_scan_at": "2026-06-07T11:40:00Z",
  "last_notification_at": "2026-06-07T11:45:00Z"
}
```

### `DELETE /scopes/{scope_id}` → 204 · 404

---

### Scope result endpoints

These return the assets discovered by the scan pipeline for a scope. All use
**offset/limit pagination**, and several accept a keyset `after` cursor for
efficient deep pagination (pass the last row's key to get the next page).

#### `GET /scopes/{scope_id}/subdomains` → 200 `[SubdomainResponse]` · 404

| Query    | Type   | Default | Constraints | Notes                          |
| -------- | ------ | ------- | ----------- | ------------------------------ |
| `offset` | int    | 0       | ≥ 0         |                                |
| `limit`  | int    | 2000    | 1–10000     |                                |
| `after`  | string | —       |             | keyset: rows after this subdomain |

**`SubdomainResponse`**
```json
{
  "id": "a1b2c3d4-e5f6-7890-ab12-cd34ef567890",
  "subdomain": "api.example.com",
  "source": "assetfinder,subfinder",
  "first_seen": "2026-06-07T12:00:00Z",
  "last_seen": "2026-06-07T12:05:00Z",
  "scope_id": "e1f8b619-1841-4b72-9ebb-9a5b70b6ed5f",
  "program_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "asset_id": "f1e2d3c4-b5a6-7890-cd12-ef34ab567890",
  "created_at": "2026-06-07T12:00:00Z",
  "updated_at": "2026-06-07T12:05:00Z"
}
```

#### `GET /scopes/{scope_id}/hosts` → 200 `[HostResponse]` · 404

| Query       | Type   | Default | Constraints | Notes                              |
| ----------- | ------ | ------- | ----------- | ---------------------------------- |
| `offset`    | int    | 0       | ≥ 0         |                                    |
| `limit`     | int    | 2000    | 1–10000     |                                    |
| `after`     | string | —       |             | keyset: host FQDN after which      |
| `live_only` | bool   | false   |             | only hosts with an HTTP status code |

**`HostResponse`**
```json
{
  "id": "…", "asset_id": "…", "program_id": "…", "scope_id": "…",
  "host": "api.example.com",
  "ip": "93.184.216.34",
  "scheme": "https", "port": 443,
  "status_code": 200, "title": "API Gateway",
  "content_length": 1024, "response_time": 0.142,
  "cdn": false, "waf": true,
  "first_seen": "2026-06-07T12:00:00Z", "last_seen": "2026-06-07T12:05:00Z",
  "created_at": "…", "updated_at": "…"
}
```

#### `GET /scopes/{scope_id}/dns-records` → 200 `[DnsRecordResponse]` · 404

| Query         | Type   | Default | Constraints | Notes                                   |
| ------------- | ------ | ------- | ----------- | --------------------------------------- |
| `record_type` | string | —       |             | filter: A, AAAA, CNAME, MX, TXT, NS     |
| `offset`      | int    | 0       | ≥ 0         |                                         |
| `limit`       | int    | 2000    | 1–10000     |                                         |

**`DnsRecordResponse`**
```json
{
  "id": "…", "program_id": "…", "scope_id": "…", "host_id": "…",
  "subdomain_id": "…", "subdomain": "api.example.com",
  "record_type": "A", "record_value": "93.184.216.34", "ttl": 300,
  "created_at": "…", "updated_at": "…"
}
```

#### `GET /scopes/{scope_id}/http-responses` → 200 `[HttpResponseResponse]` · 404

| Query         | Type | Default | Constraints | Notes                  |
| ------------- | ---- | ------- | ----------- | ---------------------- |
| `status_code` | int  | —       |             | filter by HTTP status  |
| `offset`      | int  | 0       | ≥ 0         |                        |
| `limit`       | int  | 2000    | 1–10000     |                        |

**`HttpResponseResponse`**
```json
{
  "id": "…", "program_id": "…", "scope_id": "…", "host_id": "…",
  "url": "https://api.example.com",
  "status_code": 200, "title": "API Gateway",
  "content_length": 1024, "server": "nginx",
  "technologies": ["nginx", "react"],
  "response_time": 0.142,
  "created_at": "…", "updated_at": "…"
}
```

#### `GET /scopes/{scope_id}/technologies` → 200 `[TechnologyResponse]` · 404

| Query    | Type | Default | Constraints |
| -------- | ---- | ------- | ----------- |
| `offset` | int  | 0       | ≥ 0         |
| `limit`  | int  | 2000    | 1–10000     |

**`TechnologyResponse`**
```json
{
  "id": "…", "program_id": "…", "scope_id": "…", "host_id": "…",
  "technology": "nginx", "version": "1.25.3", "confidence": 100,
  "first_seen": "2026-06-07T12:00:00Z", "last_seen": "2026-06-07T12:05:00Z",
  "created_at": "…", "updated_at": "…"
}
```

#### `GET /scopes/{scope_id}/urls` → 200 `PaginatedUrls` · 404

Content discovery (Phase 5). Returns discovered URLs for the scope.

| Query      | Type | Default          | Constraints                              |
| ---------- | ---- | ---------------- | ---------------------------------------- |
| `offset`   | int  | 0                | ≥ 0                                      |
| `limit`    | int  | 2000             | 1–10000                                  |
| `search`   | str  | —                | substring match on `normalized_url`      |
| `source`   | str  | —                | filter by tool (`GAU`, `KATANA`, …)      |
| `sort_by`  | str  | `normalized_url` | one of normalized_url, url, depth, parameter_count, extension, first_seen, last_seen, created_at |
| `sort_dir` | str  | `asc`            | `asc` or `desc`                          |

**`PaginatedUrls`**
```json
{
  "total": 1258, "offset": 0, "limit": 2000,
  "items": [{
    "id": "…", "program_id": "…", "scope_id": "…", "host_id": "…",
    "url": "https://www.example.com/login",
    "normalized_url": "https://www.example.com/login",
    "scheme": "https", "host": "www.example.com", "path": "/login",
    "query": null, "fragment": null, "extension": null,
    "directory": "/login/", "filename": null, "depth": 1,
    "parameter_count": 0, "has_parameters": false, "status": null,
    "source": "GAU,KATANA,WAYBACKURLS",
    "first_seen": "…", "last_seen": "…", "created_at": "…", "updated_at": "…"
  }]
}
```

#### `GET /scopes/{scope_id}/js-files` → 200 `PaginatedJsFiles` · 404

| Query      | Type | Default | Constraints                    |
| ---------- | ---- | ------- | ------------------------------ |
| `offset`   | int  | 0       | ≥ 0                            |
| `limit`    | int  | 2000    | 1–10000                        |
| `search`   | str  | —       | substring match on `url`       |
| `sort_by`  | str  | `url`   | url, filename, extension, first_seen, last_seen, created_at |
| `sort_dir` | str  | `asc`   | `asc` or `desc`                |

**`PaginatedJsFiles`**
```json
{
  "total": 142, "offset": 0, "limit": 2000,
  "items": [{
    "id": "…", "program_id": "…", "scope_id": "…", "host_id": "…",
    "url": "https://www.example.com/app/main.bundle.js",
    "filename": "main.bundle.js", "directory": "/app/", "extension": "js",
    "source": "KATANA,HAKRAWLER",
    "first_seen": "…", "last_seen": "…", "created_at": "…", "updated_at": "…"
  }]
}
```

---

## 4. Scans module

`backend/api/scan_routes.py` · prefix `/scans` · schemas in `scan_schema.py`

Scans are **asynchronous**: `POST /scans/start` returns `202` immediately with a
PENDING `ScanRun`; a Celery worker then runs the pipeline and updates the row.
Poll `GET /scans/{id}` (or `/report`) for progress. See
[README → The Scan Pipeline](README.md#the-scan-pipeline).

### Schemas

**`ScanStartRequest`** (request)

| Field        | Type | Required | Default       | Notes                     |
| ------------ | ---- | -------- | ------------- | ------------------------- |
| `program_id` | UUID | yes      | —             |                           |
| `scope_id`   | UUID | yes      | —             |                           |
| `scan_type`  | str  | no       | `"SUBDOMAIN"` | `SUBDOMAIN` \| `DNS` \| `HTTP` \| `CONTENT_DISCOVERY` |

**`ScanRunResponse`** — pipeline metrics are 0 until the worker fills them in.

| Field | Type | Group |
| ----- | ---- | ----- |
| `id`, `program_id`, `scope_id` | UUID | identity |
| `target` | string\|null | scope target (joined in) |
| `scan_type`, `worker_name`, `status` | string | |
| `records_found` | int | legacy aggregate (= `unique_count`) |
| `subfinder_count`, `assetfinder_count`, `merged_count`, `unique_count`, `new_count`, `existing_count` | int | subdomain phase |
| `dnsx_count`, `resolved_count`, `new_hosts_count` | int | DNS phase |
| `httpx_count`, `live_count`, `new_live_count` | int | HTTP phase |
| `error_message` | string\|null | set on FAILED |
| `started_at` | datetime | |
| `finished_at` | datetime\|null | |
| `created_at`, `updated_at` | datetime | |

`status` ∈ `PENDING, RUNNING, COMPLETED, FAILED, CANCELLED`.

---

### `POST /scans/start` → 202 `ScanRunResponse` · 400 · 404 · 409

Queue a scan for a program + scope. `409` if the scope is already being scanned
(a Redis lock is held); `404` if program/scope missing; `400` on unsupported
`scan_type`.

**Request**
```json
{
  "program_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "scope_id": "e1f8b619-1841-4b72-9ebb-9a5b70b6ed5f",
  "scan_type": "SUBDOMAIN"
}
```
**Response 202** (just queued — metrics zero, status PENDING)
```json
{
  "id": "9a1d2b3c-4e5f-6789-ab12-cd34ef567890",
  "program_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "scope_id": "e1f8b619-1841-4b72-9ebb-9a5b70b6ed5f",
  "target": "example.com",
  "scan_type": "SUBDOMAIN",
  "worker_name": "subdomain_worker",
  "status": "PENDING",
  "records_found": 0,
  "subfinder_count": 0, "assetfinder_count": 0, "merged_count": 0,
  "unique_count": 0, "new_count": 0, "existing_count": 0,
  "dnsx_count": 0, "resolved_count": 0, "new_hosts_count": 0,
  "httpx_count": 0, "live_count": 0, "new_live_count": 0,
  "error_message": null,
  "started_at": "2026-06-07T12:00:00Z",
  "finished_at": null,
  "created_at": "2026-06-07T12:00:00Z",
  "updated_at": "2026-06-07T12:00:00Z"
}
```
**Response 409**
```json
{ "detail": "Scope scan is already in progress: e1f8b619-…" }
```

### `GET /scans` → 200 `[ScanRunResponse]`

List scan runs, optionally filtered.

| Query        | Type | Notes              |
| ------------ | ---- | ------------------ |
| `program_id` | UUID | optional filter    |
| `scope_id`   | UUID | optional filter    |

### `GET /scans/{scan_run_id}` → 200 `ScanRunResponse` · 404

Get a single scan run (poll this for status/metrics).

### `GET /scans/{scan_run_id}/subdomains` → 200 `[SubdomainResponse]` · 404

Subdomains discovered during the scan (by its scope).

| Query    | Type   | Default | Constraints | Notes                  |
| -------- | ------ | ------- | ----------- | ---------------------- |
| `offset` | int    | 0       | ≥ 0         |                        |
| `limit`  | int    | 2000    | 1–10000     |                        |
| `after`  | string | —       |             | keyset cursor          |

Response item shape = [`SubdomainResponse`](#get-scopesscope_idsubdomains--200-subdomainresponse--404).

### `GET /scans/{scan_run_id}/report` → 200 `ScanReportResponse` · 404

Per-tool report: each tool's raw vs. in-scope counts, status, timings, plus two
computed fields — `duration_seconds` and a human `summary`.

**`ToolExecutionSummary`** (item)

| Field | Type | Notes |
| ----- | ---- | ----- |
| `id` | UUID | |
| `tool_name` | string | |
| `status` | string | PENDING/RUNNING/COMPLETED/FAILED |
| `raw_records_found` | int | all lines returned by the tool |
| `records_found` | int | in-scope after filtering |
| `error_message` | string\|null | |
| `started_at`, `finished_at` | datetime\|null | |
| `duration_seconds` | float\|null | computed |

**Response 200**
```json
{
  "id": "9a1d2b3c-4e5f-6789-ab12-cd34ef567890",
  "program_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "scope_id": "e1f8b619-1841-4b72-9ebb-9a5b70b6ed5f",
  "target": "example.com",
  "scan_type": "SUBDOMAIN",
  "status": "COMPLETED",
  "subfinder_count": 1300, "assetfinder_count": 900,
  "merged_count": 2200, "unique_count": 1423,
  "new_count": 87, "existing_count": 1336,
  "dnsx_count": 0, "resolved_count": 0, "new_hosts_count": 0,
  "httpx_count": 0, "live_count": 0, "new_live_count": 0,
  "records_found": 1423,
  "error_message": null,
  "started_at": "2026-06-07T12:00:00Z",
  "finished_at": "2026-06-07T12:02:22Z",
  "duration_seconds": 142.6,
  "tools": [
    {
      "id": "…", "tool_name": "subfinder", "status": "COMPLETED",
      "raw_records_found": 2200, "records_found": 1300,
      "error_message": null,
      "started_at": "2026-06-07T12:00:01Z",
      "finished_at": "2026-06-07T12:00:32Z",
      "duration_seconds": 31.2
    },
    {
      "id": "…", "tool_name": "crtsh", "status": "FAILED",
      "raw_records_found": 0, "records_found": 0,
      "error_message": "timeout",
      "started_at": "2026-06-07T12:01:00Z",
      "finished_at": "2026-06-07T12:01:02Z",
      "duration_seconds": 2.0
    }
  ],
  "summary": "subfinder: 2200 raw → 1300 in-scope | crtsh: FAILED (timeout)"
}
```

### `DELETE /scans/{scan_run_id}` → 204 · 404 · 409

Delete a scan run. **`409`** if the scan is still `PENDING` or `RUNNING` — only
`COMPLETED`, `FAILED`, or `CANCELLED` scans can be deleted.

```json
{ "detail": "Cannot delete a scan in 'RUNNING' state. Only COMPLETED, FAILED, or CANCELLED scans can be deleted." }
```

---

## Error response shape

Every non-2xx response uses the same envelope:

```json
{ "detail": "Program not found: d290f1ee-6c54-4b01-90e6-d701748f0851" }
```

For `422` validation errors, FastAPI returns its standard structure:

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "name"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```
