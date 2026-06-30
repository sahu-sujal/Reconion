# Recon Platform — Backend

An asynchronous attack-surface reconnaissance platform. A **FastAPI** REST API
accepts scan requests and persists results to **PostgreSQL**; a **Celery** worker
pool (brokered by **Redis**) runs the actual reconnaissance pipeline — subdomain
enumeration → DNS resolution → HTTP probing — chaining each phase automatically
and notifying via Discord on completion.

---

## Table of Contents

1. [Tech Stack](#tech-stack)
2. [Module Hierarchy](#module-hierarchy)
3. [Layered Architecture](#layered-architecture)
4. [End-to-End Workflow](#end-to-end-workflow)
5. [The Scan Pipeline](#the-scan-pipeline)
6. [API Reference (Request / Response)](#api-reference-request--response)
7. [Data Model](#data-model)
8. [On-Disk Storage Layout](#on-disk-storage-layout)
9. [Configuration](#configuration)
10. [Running the Backend](#running-the-backend)

---

## Tech Stack

| Concern            | Technology                                   |
| ------------------ | -------------------------------------------- |
| Web API            | FastAPI + Uvicorn                            |
| Validation / DTOs  | Pydantic v2                                  |
| ORM                | SQLAlchemy 2.x                              |
| Database           | PostgreSQL                                  |
| Migrations         | Alembic                                     |
| Task queue         | Celery 5 (worker + beat)                    |
| Broker / result    | Redis                                       |
| Notifications      | Discord webhook                            |

---

## Module Hierarchy

```
backend/                         ← repository root for the service
│
├── backend/                     ← FastAPI application package
│   ├── main.py                  ← app factory: CORS, logging, routers, error handlers
│   ├── celery_app.py            ← Celery app + task registry (include=[...])
│   ├── dependencies.py          ← get_db() request-scoped Session dependency
│   ├── exceptions.py            ← APIError / EntityNotFoundError / ScanLockedError
│   │
│   ├── api/                     ← HTTP layer (routers) — thin, no business logic
│   │   ├── health_routes.py     ← GET /health
│   │   ├── program_routes.py    ← /programs CRUD + scopes + stats
│   │   ├── scope_routes.py      ← /scopes CRUD + results (subdomains/hosts/dns/http/tech)
│   │   └── scan_routes.py       ← /scans start / list / get / report / subdomains / delete
│   │
│   ├── schemas/                 ← Pydantic request & response models (DTOs)
│   │   ├── program_schema.py
│   │   ├── scope_schema.py
│   │   ├── scan_schema.py
│   │   ├── host_schema.py
│   │   └── subdomain_schema.py
│   │
│   ├── services/                ← business logic / orchestration
│   │   ├── program_service.py
│   │   ├── scope_service.py
│   │   ├── scan_service.py      ← acquires scope lock, creates ScanRun, dispatches task
│   │   ├── scan_run_service.py
│   │   ├── program_settings_service.py
│   │   └── storage_service.py   ← UUID-keyed on-disk artifact tree
│   │
│   └── queues/
│       └── redis_client.py      ← Redis client + scope lock (acquire/release/is_locked)
│
├── workers/                     ← Celery tasks — the recon pipeline
│   ├── base/base_worker.py      ← DB session + mark_running/completed/failed helpers
│   ├── subdomain/subdomain_worker.py  ← Phase 1: enumerate → merge → upsert → chain DNS
│   ├── dns/dns_worker.py        ← Phase 2: dnsx resolve → hosts → chain HTTP
│   ├── http/http_worker.py      ← Phase 3: httpx probe → live hosts + technologies
│   ├── notification/discord_worker.py ← Discord embed on scan completion
│   └── scheduler/scan_scheduler.py    ← Celery beat heartbeat (every 5 min)
│
├── tools/                       ← thin wrappers around external CLI recon tools
│   ├── common/                  ← command_runner, scope_filter, dedupe_utils, file_utils, tool_base
│   ├── subdomain/               ← subfinder, assetfinder, knockpy, dnsgen, chaos, crtsh, findomain
│   ├── dns/dnsx_runner.py
│   └── http/httpx_runner.py
│
├── repositories/                ← data-access layer (one repo per aggregate)
│   ├── base_repository.py
│   └── *_repository.py          ← program, scope, scan_run, subdomain, host, dns_record, …
│
├── database/                    ← SQLAlchemy engine, Base, session, ORM models
│   ├── config.py                ← builds DATABASE_URL from env
│   ├── base.py / session.py
│   └── models/*.py              ← program, scope, scan_run, subdomain, host, … + enums.py
│
├── alembic/                     ← migration environment + versions/
├── scripts/                     ← test_db.py and other one-offs
├── tests/                       ← pytest (test_phase4_e2e.py)
├── alembic.ini · pytest.ini · .env
```

### Why these layers

Requests flow **top-down** and never skip a layer:

```
api/ (HTTP)  →  services/ (orchestration)  →  repositories/ (data access)  →  database/ (ORM/SQL)
```

Workers reuse the **same** `services/`, `repositories/`, `tools/`, and `database/`
layers, so business rules live in exactly one place regardless of whether the
caller is an HTTP request or a background task.

---

## Layered Architecture

| Layer            | Package         | Responsibility                                                                 |
| ---------------- | --------------- | ------------------------------------------------------------------------------ |
| **API**          | `backend/api`   | Parse/validate input (Pydantic), call a service, map domain errors → HTTP codes. No SQL, no business rules. |
| **Schema (DTO)** | `backend/schemas` | Define request bodies and response shapes; `from_attributes=True` lets responses be built directly from ORM rows. |
| **Service**      | `backend/services` | Orchestrate use-cases: validate references, enforce locks, create `ScanRun`, dispatch Celery tasks, assemble reports. |
| **Repository**   | `repositories`  | All persistence. Query/insert/upsert/delete; keyset pagination; bulk `ON CONFLICT` upserts. |
| **Model**        | `database/models` | SQLAlchemy ORM entities + enums; the canonical schema.                       |
| **Worker**       | `workers`       | Long-running Celery tasks that drive the recon pipeline and write results.    |
| **Tool**         | `tools`         | Subprocess wrappers around external binaries; each exposes `run(target) -> list[str]`. |

---

## End-to-End Workflow

```
                       HTTP (FastAPI / Uvicorn)              Async (Celery worker + Redis)
   ┌────────┐   POST /scans/start    ┌──────────────┐  send_task   ┌──────────────────────┐
   │ Client │ ─────────────────────► │ scan_routes  │ ───────────► │  Redis broker queue  │
   └────────┘                        └──────┬───────┘              └──────────┬───────────┘
        ▲                                   │                                  │ picks up task
        │ 202 Accepted (ScanRun PENDING)    ▼                                  ▼
        │                            ┌──────────────┐               ┌──────────────────────┐
        └─────────────────────────  │ ScanService  │               │  subdomain_worker    │
                                     │ • verify prog│               │  → dns_worker        │
                                     │ • verify scope│              │  → http_worker       │
                                     │ • acquire lock│              └──────────┬───────────┘
                                     │ • create RUN │                          │ writes
                                     │ • dispatch   │                          ▼
                                     └──────────────┘               ┌──────────────────────┐
                                                                    │ PostgreSQL + storage/│
                                                                    │ + Discord webhook    │
                                                                    └──────────────────────┘
```

**Step by step:**

1. **Client** creates a Program (`POST /programs`) and a Scope (`POST /scopes`)
   pointing at a root domain (e.g. `example.com`).
2. **Client** triggers a scan (`POST /scans/start`). The request is *non-blocking*.
3. **`ScanService.start_scan`**:
   - Verifies the program and scope exist.
   - Acquires a **Redis scope lock** (`scan_lock:{scope_id}`, 30-min TTL) so the
     same scope can't run two scans concurrently. If already locked and the last
     scan is still PENDING/RUNNING → **409 Conflict** (`ScanLockedError`).
   - Creates a `ScanRun` row with status **PENDING**.
   - `celery_app.send_task(...)` enqueues the worker task (1 s countdown).
   - Returns **202 Accepted** with the `ScanRun` (the client polls for progress).
4. A **Celery worker** picks the task up from Redis and runs the pipeline below,
   updating `ScanRun.status` PENDING → RUNNING → COMPLETED/FAILED and persisting
   results.
5. On completion the worker **chains the next phase** and fires a **Discord**
   notification.
6. **Client polls** `GET /scans/{id}` (status + metrics) and reads discovered
   assets via the `/scopes/{id}/...` result endpoints.

---

## The Scan Pipeline

Each scan type is a separate Celery task. Workers **auto-chain** to the next
phase, so a single `SUBDOMAIN` scan drives the whole pipeline:

```
SUBDOMAIN ──(if unique>0)──► DNS ──(if new hosts)──► HTTP
```

### Phase 1 — Subdomain enumeration  (`subdomain_worker.py`)

1. Run 7 enumeration tools, each isolated (one failure never aborts the scan):
   **subfinder, assetfinder, knockpy, dnsgen, chaos, crtsh, findomain**.
2. Save each tool's raw output to `…/subdomains/raw/<tool>.txt`.
3. Filter every result to in-scope names (must equal or end with `.<target>`).
4. **Disk-based `sort -u` merge** of all raw files → `processed/subdomains.txt`
   (avoids loading 100k+ entries into memory).
5. **Bulk upsert** subdomains via `ON CONFLICT (scope_id, subdomain)` in 50k batches;
   record per-subdomain source tools in `subdomain_sources`.
6. Write a diff file of only the **new** subdomains: `diff/<timestamp>-new.txt`.
7. Update `ScanRun` metric columns (per-tool counts, merged/unique/new/existing).
8. Send a Discord embed with a summary + new-asset sample.
9. **Chain a DNS scan** for the same scope.

### Phase 2 — DNS resolution  (`dns_worker.py`)

- Feeds discovered subdomains to **dnsx**, persists resolved **hosts** and
  **dns_records**, updates `dnsx_count / resolved_count / new_hosts_count`, then
  **chains an HTTP scan**.

### Phase 3 — HTTP probing  (`http_worker.py`)

- Probes resolved hosts with **httpx**, persists **http_responses** and detected
  **technologies**, marks live hosts, updates `httpx_count / live_count /
  new_live_count`. End of the chain.

> Every tool invocation is recorded as a `tool_executions` row (status, raw vs.
> in-scope record counts, error message, timings) — surfaced via the scan report.

### Scheduler  (`scan_scheduler.py`)

Celery **beat** fires `enqueue_pending_scans` every 5 minutes as a heartbeat for
pending work. (Requires `celery beat` to be running alongside the worker.)

---

## API Reference (Request / Response)

Base URL: `http://localhost:8000` · Interactive docs: **`/docs`** (Swagger) and
**`/redoc`**. All IDs are UUIDs; all timestamps are UTC ISO-8601.

### Conventions

- Request bodies are JSON; create/update schemas use `extra="forbid"` — unknown
  fields are rejected with **422**.
- Error envelope is always `{"detail": "<message>"}`.

| Status | Meaning                                                |
| ------ | ------------------------------------------------------ |
| 200    | OK                                                     |
| 201    | Created (program / scope)                              |
| 202    | Accepted — scan queued (async)                         |
| 204    | No Content (delete)                                    |
| 400    | Bad request (`ValueError` / `APIError`)                |
| 404    | Entity not found (`EntityNotFoundError`)               |
| 409    | Conflict — scope already scanning, or deleting a running scan |
| 422    | Validation error (FastAPI/Pydantic)                    |
| 500    | Internal server error                                  |

### Health

```
GET /health  →  200
{ "status": "ok", "service": "recon-platform" }
```

### Programs  (`/programs`)

| Method & path                 | Body / query                   | Returns                          |
| ----------------------------- | ------------------------------ | -------------------------------- |
| `POST /programs`              | `ProgramCreate`                | `201 ProgramResponse`            |
| `GET /programs`               | —                              | `200 [ProgramResponse]`          |
| `GET /programs/{id}`          | —                              | `200 ProgramResponse` / 404      |
| `PATCH /programs/{id}`        | `ProgramUpdate`                | `200 ProgramResponse` / 404      |
| `GET /programs/{id}/scopes`   | `offset, limit` (≤250)         | `200 [ScopeResponse]` / 404      |
| `GET /programs/{id}/stats`    | —                              | `200 ProgramStatsResponse` / 404 |
| `DELETE /programs/{id}`       | —                              | `204` / 404                      |

**Create request → response**

```jsonc
// POST /programs
{ "name": "Recon Project", "platform": "aws",
  "description": "External asset monitoring", "status": "active" }
```
```jsonc
// 201 Created
{ "id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "name": "Recon Project", "platform": "aws", "status": "active",
  "description": "External asset monitoring", "created_by": null,
  "created_at": "2026-06-07T00:00:00Z", "updated_at": "2026-06-07T00:00:00Z" }
```

`ProgramStatsResponse` aggregates: `total_scopes, active_scopes, total_assets,
total_subdomains, total_hosts, live_hosts, total_dns_records, total_technologies,
total_findings, open_findings, total_scan_runs, total_notifications,
last_scan_at, last_notification_at`.

### Scopes  (`/scopes`)

| Method & path                          | Body / query                         | Returns                              |
| -------------------------------------- | ------------------------------------ | ------------------------------------ |
| `POST /scopes`                         | `ScopeCreate`                        | `201 ScopeResponse` / 400 / 404      |
| `GET /scopes?program_id=`              | optional `program_id`                | `200 [ScopeResponse]`                |
| `GET /scopes/{id}`                     | —                                    | `200 ScopeResponse` / 404            |
| `PATCH /scopes/{id}`                   | `ScopeUpdate`                        | `200 ScopeResponse` / 400 / 404      |
| `GET /scopes/{id}/stats`               | —                                    | `200 ScopeStatsResponse` / 404       |
| `DELETE /scopes/{id}`                  | —                                    | `204` / 404                          |
| `GET /scopes/{id}/subdomains`          | `offset, limit (≤10000), after`      | `200 [SubdomainResponse]` / 404      |
| `GET /scopes/{id}/hosts`               | `offset, limit, after, live_only`    | `200 [HostResponse]` / 404           |
| `GET /scopes/{id}/dns-records`         | `record_type, offset, limit`         | `200 [DnsRecordResponse]` / 404      |
| `GET /scopes/{id}/http-responses`      | `status_code, offset, limit`         | `200 [HttpResponseResponse]` / 404   |
| `GET /scopes/{id}/technologies`        | `offset, limit`                      | `200 [TechnologyResponse]` / 404     |

**Create request → response**

```jsonc
// POST /scopes
{ "program_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "target": "example.com", "scope_type": "ROOT_DOMAIN",
  "priority": 50, "is_active": true, "notes": "Primary scope" }
```
```jsonc
// 201 Created
{ "id": "e1f8b619-1841-4b72-9ebb-9a5b70b6ed5f",
  "program_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "target": "example.com", "scope_type": "ROOT_DOMAIN", "priority": 50,
  "is_active": true, "notes": "Primary scope", "last_scan_at": null,
  "created_at": "2026-06-07T00:00:00Z", "updated_at": "2026-06-07T00:00:00Z" }
```

> Result endpoints (`/subdomains`, `/hosts`, …) use **keyset pagination**: pass
> the last item's key as `after=` for the next page (cheaper than large offsets).

### Scans  (`/scans`)

| Method & path                       | Body / query                        | Returns                                  |
| ----------------------------------- | ----------------------------------- | ---------------------------------------- |
| `POST /scans/start`                 | `ScanStartRequest`                  | `202 ScanRunResponse` / 400 / 404 / 409  |
| `GET /scans?program_id=&scope_id=`  | optional filters                    | `200 [ScanRunResponse]`                  |
| `GET /scans/{id}`                   | —                                   | `200 ScanRunResponse` / 404              |
| `GET /scans/{id}/subdomains`        | `offset, limit, after`              | `200 [SubdomainResponse]` / 404          |
| `GET /scans/{id}/report`            | —                                   | `200 ScanReportResponse` / 404           |
| `DELETE /scans/{id}`                | —                                   | `204` / 404 / 409 (if PENDING/RUNNING)   |

**Start a scan (async)**

```jsonc
// POST /scans/start
{ "program_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "scope_id":   "e1f8b619-1841-4b72-9ebb-9a5b70b6ed5f",
  "scan_type":  "SUBDOMAIN" }          // SUBDOMAIN | DNS | HTTP
```
```jsonc
// 202 Accepted — work is queued; poll GET /scans/{id}
{ "id": "9a1d…", "program_id": "d290…", "scope_id": "e1f8…",
  "target": "example.com", "scan_type": "SUBDOMAIN",
  "worker_name": "subdomain_worker", "status": "PENDING",
  "records_found": 0,
  "subfinder_count": 0, "assetfinder_count": 0, "merged_count": 0,
  "unique_count": 0, "new_count": 0, "existing_count": 0,
  "dnsx_count": 0, "resolved_count": 0, "new_hosts_count": 0,
  "httpx_count": 0, "live_count": 0, "new_live_count": 0,
  "error_message": null,
  "started_at": "2026-06-07T12:00:00Z", "finished_at": null,
  "created_at": "2026-06-07T12:00:00Z", "updated_at": "2026-06-07T12:00:00Z" }
```

`409 Conflict` if the scope is already being scanned (Redis lock held).

**Scan report** (`GET /scans/{id}/report`) returns `ScanReportResponse`: the same
pipeline counters plus a per-tool breakdown and two computed fields —
`duration_seconds` and a human `summary` string:

```jsonc
{ "id": "9a1d…", "scan_type": "SUBDOMAIN", "status": "COMPLETED",
  "unique_count": 1423, "new_count": 87, "records_found": 1423,
  "duration_seconds": 142.6,
  "tools": [
    { "tool_name": "subfinder", "status": "COMPLETED",
      "raw_records_found": 2200, "records_found": 1300,
      "duration_seconds": 31.2,
      "started_at": "…", "finished_at": "…" },
    { "tool_name": "crtsh", "status": "FAILED",
      "error_message": "timeout", "raw_records_found": 0, "records_found": 0 }
  ],
  "summary": "subfinder: 2200 raw → 1300 in-scope | crtsh: FAILED (timeout)" }
```

---

## Data Model

Core entities (`database/models/`) and their relationships:

```
Program 1───* Scope 1───* ScanRun 1───* ToolExecution
   │             │
   │             ├──* Subdomain ───* SubdomainSource
   │             ├──* Host ──* DnsRecord
   │             │         └──* HttpResponse
   │             │         └──* Technology
   │             └──* (Url, Finding, Notification, …)
   └──* ProgramSettings
```

Key enums (`database/models/enums.py`):

- **ScanType** — `SUBDOMAIN, DNS, HTTP, PORT, URL, JS, TECHNOLOGY, SCREENSHOT`
- **ScanStatus** — `PENDING, RUNNING, COMPLETED, FAILED, CANCELLED`
- **ToolExecutionStatus** — `PENDING, RUNNING, COMPLETED, FAILED`
- **ScopeType** — `ROOT_DOMAIN, WILDCARD_DOMAIN, SUBDOMAIN, URL, CIDR, IP_RANGE`
- **NotificationChannel** — `EMAIL, SLACK, TEAMS, WEBHOOK`

---

## On-Disk Storage Layout

Workers write raw and processed artifacts under `storage/`, keyed by UUID
(`StorageService`). Per scope:

```
storage/programs/<program_id>/scopes/<scope_id>/
├── subdomains/{raw,processed}/      ← per-tool raw + merged subdomains.txt
├── dns/{raw,processed}/             ← dnsx.json, resolved.txt
├── http/{raw,processed}/            ← httpx.json, live.txt
├── classifications/                 ← gf_* pattern matches
├── js_intelligence/                 ← linkfinder/secretfinder/etc. output
├── diff/<timestamp>-new.txt         ← only newly discovered subdomains
└── logs/                            ← per-tool CLI logs
```

> `storage/` is git-ignored (scan output, not source).

---

## Configuration

Environment is read from `backend/.env` (loaded by `database/config.py` and
`redis_client.py`):

| Variable                                            | Purpose                              | Default                      |
| --------------------------------------------------- | ------------------------------------ | ---------------------------- |
| `POSTGRES_HOST/PORT/DB/USER/PASSWORD`               | PostgreSQL connection                | localhost:5432 / recon       |
| `DB_DRIVER`                                          | SQLAlchemy driver                    | `postgresql`                 |
| `REDIS_URL`                                          | Celery broker + result backend       | `redis://localhost:6379/0`   |
| `CORS_ORIGINS`                                       | comma-separated allowed origins      | localhost:5173–5175          |
| `DISCORD_WEBHOOK_URL`                                | scan-completion notifications        | —                            |
| `ENV`                                                | environment name                     | `development`                |

`DATABASE_URL` is assembled as
`postgresql://<user>:<password>@<host>:<port>/<db>`.

---

## Running the Backend

### Prerequisites

- PostgreSQL running with the `recon` database and `reconuser` role.
- Redis available (or let the start script launch it).
- External recon CLIs on `PATH` (subfinder, assetfinder, dnsx, httpx, …) for real
  scans; missing tools are recorded as failed `tool_executions` and skipped.

### One-command start

From the repository root, [`backend_start.sh`](../backend_start.sh) activates the
virtualenv, ensures Redis is up, and launches the **Celery worker**, **Celery
beat**, and the **FastAPI** server together:

```bash
./backend_start.sh        # API on http://0.0.0.0:8000  (override API_HOST / API_PORT)
```

### Manual start

```bash
cd backend

# 1. Apply migrations
.venv/bin/python -m alembic upgrade head

# 2. API
.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

# 3. Celery worker (separate shell)
.venv/bin/python -m celery -A backend.celery_app:celery_app worker --loglevel=info

# 4. Celery beat — required for the 5-min scheduler (separate shell)
.venv/bin/python -m celery -A backend.celery_app:celery_app beat --loglevel=info
```

> The `backend/.venv` was created by `uv` at an old path and moved, so its
> `activate` script has a stale path. Invoke tools via `.venv/bin/python -m <module>`
> (uses the working `python` symlink) rather than `source .venv/bin/activate`.

### Database migrations

```bash
.venv/bin/python -m alembic upgrade head          # apply all
.venv/bin/python -m alembic revision --autogenerate -m "message"
.venv/bin/python -m alembic current               # show current head
```

### Tests

```bash
.venv/bin/python -m pytest          # see pytest.ini; tests/test_phase4_e2e.py is end-to-end
```
