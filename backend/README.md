# Recon Platform

A fully automated, production-grade reconnaissance pipeline built on FastAPI, Celery, PostgreSQL, and Redis. Orchestrates subdomain enumeration → DNS resolution → HTTP probing across multiple tools, stores all results in a normalized relational schema, and delivers structured Discord notifications at each phase.

---

## Recent Updates

- **DNS records now carry their subdomain name.** `dns_records` has a nullable
  `subdomain_id` FK → `subdomains`, and `GET /scopes/{id}/dns-records` returns a
  flattened `subdomain` (name) field alongside `subdomain_id`. This lets the
  frontend group/label DNS records by subdomain without a second lookup.
- **Fixed `GET /scopes/{id}/dns-records` 500 error.** `DnsRecordResponse` now
  extracts the subdomain name from the ORM relationship with a `mode="before"`
  field validator, so the `Subdomain` object is flattened to a string *before*
  type validation instead of raising `ResponseValidationError`.
- **Fixed `new_live_count` always reporting 0.** The HTTP worker now compares
  each host against its pre-scan `status_code` and counts hosts that become live
  for the first time in a run. First scans report `new_live_count == live_count`.
- **Widened `hosts.ip` and added migrations** (`g6b7c8d9e0f1`, `h7c8d9e0f1g2`).

---

## Table of Contents

0. [Recent Updates](#recent-updates)
1. [Architecture Overview](#architecture-overview)
2. [Database Structure & Relationships](#database-structure--relationships)
3. [API Documentation](#api-documentation)
4. [Workers & Tools](#workers--tools)
5. [Scan Pipeline & Orchestration](#scan-pipeline--orchestration)
6. [Storage Layout](#storage-layout)
7. [Discord Notifications](#discord-notifications)
8. [Environment Variables](#environment-variables)
9. [Quick Start](#quick-start)
10. [Running Tests](#running-tests)

---

## Architecture Overview

```
Client / Scheduler
       │
       ▼
FastAPI (backend/)
  ├── Routes → Services → Repositories → PostgreSQL
  └── Triggers Celery Task via Redis
               │
               ▼ (auto-chained)
     ┌─────────────────────────┐
     │  SubdomainScanWorker    │  Phase 3
     │  7 enumeration tools    │
     └────────────┬────────────┘
                  │ chains on success
                  ▼
     ┌─────────────────────────┐
     │  DnsScanWorker          │  Phase 4
     │  dnsx (A/AAAA/CNAME/    │
     │        MX/TXT/NS)       │
     └────────────┬────────────┘
                  │ chains on success
                  ▼
     ┌─────────────────────────┐
     │  HttpScanWorker         │  Phase 4
     │  httpx (status, title,  │
     │  tech-detect, CDN/WAF)  │
     └─────────────────────────┘
               │
               ▼
     PostgreSQL + Storage (UUID-keyed)
     Redis (Celery broker + scope locks)
     Discord (structured embeds per phase)
```

---

## Database Structure & Relationships

### Entity Relationship Diagram

```
Program (1)
  │
  ├── ProgramSettings (1:1)
  │
  ├──< Scope (N)
  │       │
  │       ├──< Asset (N)               ← SUBDOMAIN / HOST / URL / …
  │       │       │
  │       │       ├──< Subdomain (N)
  │       │       │       └──< SubdomainSource (N)  ← per-tool attribution
  │       │       │
  │       │       ├──< Host (N)        ← resolved + probed hosts
  │       │       │       ├──< DnsRecord (N)        ← A/AAAA/CNAME/MX/TXT/NS
  │       │       │       ├──< HttpResponse (N)     ← per-URL HTTP probe result
  │       │       │       └──< Technology (N)       ← detected tech stack
  │       │       │
  │       │       ├──< URL (N)
  │       │       └──< Finding (N)
  │       │
  │       ├──< ScanRun (N)
  │       │       ├──< ToolExecution (N)
  │       │       └──< SubdomainSource (N)
  │       │
  │       └──< Notification (N)
  │
  └──< Finding (N)
```

---

### All Models

All models share three mixins:
- **UUIDMixin** — `id: UUID` primary key
- **TimestampMixin** — `created_at`, `updated_at`
- **SoftDeleteMixin** — `is_deleted`, `deleted_at` (on Program, Scope, Asset, Finding)

---

#### `programs`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | PK |
| `name` | VARCHAR(255) | indexed |
| `platform` | VARCHAR(128) | nullable |
| `status` | VARCHAR(64) | `active` / `paused` / `archived` |
| `description` | TEXT | nullable |
| `created_by` | TEXT | nullable |
| `created_at` / `updated_at` | TIMESTAMP | auto |
| `is_deleted` / `deleted_at` | — | soft delete |

**Relationships** → scopes, settings, assets, scan_runs, findings, notifications (all cascade delete)

---

#### `scopes`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | PK |
| `program_id` | UUID | FK → programs |
| `target` | VARCHAR(255) | e.g. `example.com` |
| `scope_type` | VARCHAR(32) | `ROOT_DOMAIN` / `WILDCARD_DOMAIN` / `SUBDOMAIN` / `URL` / `CIDR` / `IP_RANGE` |
| `priority` | INTEGER | default 50 |
| `is_active` | BOOLEAN | default true |
| `last_scan_at` | TIMESTAMP | nullable |
| `notes` | TEXT | nullable |

**Unique**: `(program_id, target)` — **Relationships** → assets, scan_runs, findings, notifications

---

#### `assets`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | PK |
| `program_id` | UUID | FK → programs |
| `scope_id` | UUID | FK → scopes |
| `asset_type` | VARCHAR(32) | `SUBDOMAIN` / `HOST` / `URL` / `JS` / `CLOUD` / `IP` / `PORT` |
| `asset_value` | TEXT | indexed |
| `source` | VARCHAR(255) | tool name |
| `status` | VARCHAR(64) | |
| `first_seen` / `last_seen` | TIMESTAMP | nullable |

**Unique**: `(program_id, scope_id, asset_value)`

---

#### `subdomains`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | PK |
| `asset_id` | UUID | FK → assets, SET NULL |
| `program_id` | UUID | FK → programs |
| `scope_id` | UUID | FK → scopes |
| `subdomain` | VARCHAR(255) | |
| `source` | VARCHAR(255) | comma-sep tool names |
| `first_seen` / `last_seen` | TIMESTAMP | nullable |

**Unique**: `(scope_id, subdomain)` — **Relationships** → sources (SubdomainSource)

---

#### `subdomain_sources`

| Column | Type | Notes |
|--------|------|-------|
| `subdomain_id` | UUID | FK → subdomains |
| `scan_run_id` | UUID | FK → scan_runs |
| `tool_name` | VARCHAR(128) | |

**Unique**: `(subdomain_id, tool_name, scan_run_id)`

---

#### `hosts` *(Phase 4 extended)*

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | PK |
| `asset_id` | UUID | FK → assets |
| `program_id` | UUID | FK → programs |
| `scope_id` | UUID | FK → scopes |
| `host` | VARCHAR(255) | FQDN, indexed |
| `ip` | VARCHAR(64) | primary A record |
| `scheme` | VARCHAR(16) | `http` / `https` |
| `port` | INTEGER | e.g. 443, 8080 |
| `status_code` | INTEGER | HTTP status (null = not yet probed) |
| `title` | VARCHAR(512) | page title |
| `content_length` | INTEGER | response body length |
| `response_time` | FLOAT | milliseconds |
| `cdn` | BOOLEAN | CDN detected |
| `waf` | BOOLEAN | WAF detected |
| `first_seen` / `last_seen` | TIMESTAMP | |

**Unique**: `(scope_id, host)` — **Relationships** → dns_records, http_responses, technologies

---

#### `dns_records` *(Phase 4 new)*

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | PK |
| `program_id` | UUID | FK → programs |
| `scope_id` | UUID | FK → scopes |
| `host_id` | UUID | FK → hosts |
| `subdomain_id` | UUID | FK → subdomains, SET NULL (nullable) |
| `record_type` | VARCHAR(16) | `A` / `AAAA` / `CNAME` / `MX` / `TXT` / `NS` |
| `record_value` | TEXT | resolved value |
| `ttl` | INTEGER | nullable |

**Unique**: `(host_id, record_type, record_value)` — **Relationships** → subdomain (back-populates `dns_records`)

---

#### `http_responses` *(Phase 4 new)*

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | PK |
| `program_id` | UUID | FK → programs |
| `scope_id` | UUID | FK → scopes |
| `host_id` | UUID | FK → hosts |
| `url` | TEXT | full probed URL |
| `status_code` | INTEGER | nullable |
| `title` | VARCHAR(512) | nullable |
| `content_length` | INTEGER | nullable |
| `server` | VARCHAR(255) | `Server:` header |
| `technologies` | JSONB | array of `"Name:version"` strings |
| `response_time` | FLOAT | ms |

**Unique**: `(host_id, url)`

---

#### `technologies`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | PK |
| `program_id` | UUID | FK → programs |
| `scope_id` | UUID | FK → scopes |
| `host_id` | UUID | FK → hosts |
| `technology` | VARCHAR(128) | e.g. `Nginx` |
| `version` | VARCHAR(64) | nullable |
| `confidence` | INTEGER | nullable |
| `first_seen` / `last_seen` | TIMESTAMP | |

---

#### `scan_runs`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | PK |
| `program_id` | UUID | FK → programs |
| `scope_id` | UUID | FK → scopes |
| `scan_type` | VARCHAR(32) | `SUBDOMAIN` / `DNS` / `HTTP` / `PORT` / `URL` / `JS` / `TECHNOLOGY` / `SCREENSHOT` |
| `worker_name` | VARCHAR(255) | |
| `status` | ENUM | `PENDING` / `RUNNING` / `COMPLETED` / `FAILED` / `CANCELLED` |
| `records_found` | INTEGER | total |
| **Subdomain metrics** | | |
| `subfinder_count` | INTEGER | |
| `assetfinder_count` | INTEGER | |
| `knockpy_count` | INTEGER | |
| `dnsgen_count` | INTEGER | |
| `chaos_count` | INTEGER | |
| `crtsh_count` | INTEGER | |
| `findomain_count` | INTEGER | |
| `merged_count` | INTEGER | after disk-merge |
| `unique_count` | INTEGER | after dedup |
| `new_count` | INTEGER | newly in DB |
| `existing_count` | INTEGER | already in DB |
| **DNS metrics** | | |
| `dnsx_count` | INTEGER | subdomains sent to dnsx |
| `resolved_count` | INTEGER | hosts resolved |
| `new_hosts_count` | INTEGER | newly inserted hosts |
| **HTTP metrics** | | |
| `httpx_count` | INTEGER | hosts probed |
| `live_count` | INTEGER | hosts responded |
| `new_live_count` | INTEGER | newly live |
| `error_message` | TEXT | nullable |
| `started_at` / `finished_at` | TIMESTAMP | |

---

#### `tool_executions`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | PK |
| `scan_run_id` | UUID | FK → scan_runs |
| `tool_name` | VARCHAR(128) | |
| `command` | TEXT | full CLI string |
| `status` | ENUM | `PENDING` / `RUNNING` / `COMPLETED` / `FAILED` |
| `raw_records_found` | INTEGER | before scope filter |
| `records_found` | INTEGER | after scope filter |
| `error_message` | TEXT | nullable |
| `started_at` / `finished_at` | TIMESTAMP | |

---

#### `findings`

| Column | Type | Notes |
|--------|------|-------|
| `severity` | ENUM | `CRITICAL` / `HIGH` / `MEDIUM` / `LOW` / `INFO` |
| `status` | ENUM | `NEW` / `REVIEWING` / `CONFIRMED` / `FALSE_POSITIVE` / `CLOSED` |
| `confidence` | INTEGER | 0–100 |

---

#### `notifications`

| Column | Type | Notes |
|--------|------|-------|
| `channel` | ENUM | `EMAIL` / `SLACK` / `TEAMS` / `WEBHOOK` |
| `sent` | BOOLEAN | |
| `sent_at` | TIMESTAMP | nullable |

---

## API Documentation

Base URL: `http://localhost:8000`  
Interactive docs: `/docs` (Swagger UI) | `/redoc`

---

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Service liveness check |

**Response 200**
```json
{ "status": "ok", "service": "recon-platform" }
```

---

### Programs

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/programs` | 201 | Create program |
| `GET` | `/programs` | 200 | List all programs |
| `GET` | `/programs/{id}` | 200 | Get program |
| `PATCH` | `/programs/{id}` | 200 | Update metadata |
| `DELETE` | `/programs/{id}` | 204 | Soft delete |
| `GET` | `/programs/{id}/scopes` | 200 | List scopes (`offset`, `limit`) |
| `GET` | `/programs/{id}/stats` | 200 | Aggregate stats |

#### `GET /programs/{id}/stats` — Response 200

```json
{
  "program_id": "uuid",
  "total_scopes": 12,
  "active_scopes": 10,
  "total_assets": 3400,
  "total_subdomains": 2800,
  "total_hosts": 420,
  "live_hosts": 310,
  "total_dns_records": 1850,
  "total_technologies": 94,
  "total_findings": 22,
  "open_findings": 5,
  "total_scan_runs": 48,
  "total_notifications": 9,
  "last_scan_at": "2026-06-10T12:00:00Z",
  "last_notification_at": "2026-06-10T12:05:00Z"
}
```

---

### Scopes

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/scopes` | 201 | Create scope |
| `GET` | `/scopes` | 200 | List (`program_id` filter) |
| `GET` | `/scopes/{id}` | 200 | Get scope |
| `PATCH` | `/scopes/{id}` | 200 | Update |
| `DELETE` | `/scopes/{id}` | 204 | Soft delete |
| `GET` | `/scopes/{id}/stats` | 200 | Asset/finding counts |
| `GET` | `/scopes/{id}/subdomains` | 200 | Subdomains (keyset pagination) |
| `GET` | `/scopes/{id}/hosts` | 200 | **[Phase 4]** Resolved hosts |
| `GET` | `/scopes/{id}/dns-records` | 200 | **[Phase 4]** DNS records |
| `GET` | `/scopes/{id}/http-responses` | 200 | **[Phase 4]** HTTP probe results |
| `GET` | `/scopes/{id}/technologies` | 200 | **[Phase 4]** Detected technologies |

#### `GET /scopes/{id}/subdomains` query params

| Param | Default | Max | Notes |
|-------|---------|-----|-------|
| `offset` | 0 | — | |
| `limit` | 2000 | 10000 | |
| `after` | — | — | Keyset cursor (subdomain string) |

#### `GET /scopes/{id}/hosts` query params

| Param | Default | Notes |
|-------|---------|-------|
| `offset` | 0 | |
| `limit` | 2000 | max 10000 |
| `after` | — | Keyset cursor (host FQDN) |
| `live_only` | `false` | When `true` returns only hosts with `status_code != null` |

#### `GET /scopes/{id}/dns-records` query params

| Param | Notes |
|-------|-------|
| `record_type` | Optional filter: `A`, `AAAA`, `CNAME`, `MX`, `TXT`, `NS` |
| `offset` / `limit` | Pagination |

#### `GET /scopes/{id}/http-responses` query params

| Param | Notes |
|-------|-------|
| `status_code` | Optional integer filter |
| `offset` / `limit` | Pagination |

---

### Scans

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/scans/start` | 202 | Start a scan |
| `GET` | `/scans` | 200 | List (`program_id`, `scope_id` filters) |
| `GET` | `/scans/{id}` | 200 | Get scan run |
| `GET` | `/scans/{id}/subdomains` | 200 | Subdomains for this scan |
| `GET` | `/scans/{id}/report` | 200 | Full per-tool report |
| `DELETE` | `/scans/{id}` | 204 | Delete (COMPLETED/FAILED/CANCELLED only) |

#### `POST /scans/start` — Request body

```json
{
  "program_id": "uuid",
  "scope_id": "uuid",
  "scan_type": "SUBDOMAIN"
}
```

`scan_type` values: `SUBDOMAIN` (default), `DNS`, `HTTP`

**Error 409** — scope already has an active scan (Redis lock held)

#### `GET /scans/{id}` — Response 200

```json
{
  "id": "uuid",
  "program_id": "uuid",
  "scope_id": "uuid",
  "target": "example.com",
  "scan_type": "SUBDOMAIN",
  "worker_name": "subdomain_worker",
  "status": "COMPLETED",
  "records_found": 842,
  "subfinder_count": 310,
  "assetfinder_count": 180,
  "merged_count": 900,
  "unique_count": 860,
  "new_count": 42,
  "existing_count": 800,
  "dnsx_count": 0,
  "resolved_count": 0,
  "new_hosts_count": 0,
  "httpx_count": 0,
  "live_count": 0,
  "new_live_count": 0,
  "error_message": null,
  "started_at": "...",
  "finished_at": "...",
  "created_at": "...",
  "updated_at": "..."
}
```

#### `GET /scans/{id}/report` — Response 200

```json
{
  "id": "uuid",
  "scan_type": "SUBDOMAIN",
  "status": "COMPLETED",
  "subfinder_count": 310,
  "resolved_count": 0,
  "live_count": 0,
  "duration_seconds": 187.4,
  "summary": "subfinder: 320 raw → 310 in-scope | assetfinder: ...",
  "tools": [
    {
      "tool_name": "subfinder",
      "status": "COMPLETED",
      "raw_records_found": 320,
      "records_found": 310,
      "duration_seconds": 45.2
    }
  ]
}
```

---

### Response Schemas — Phase 4 new

#### `HostResponse`

```json
{
  "id": "uuid",
  "asset_id": "uuid",
  "program_id": "uuid",
  "scope_id": "uuid",
  "host": "api.example.com",
  "ip": "93.184.216.34",
  "scheme": "https",
  "port": 443,
  "status_code": 200,
  "title": "API Gateway",
  "content_length": 4821,
  "response_time": 42.3,
  "cdn": false,
  "waf": false,
  "first_seen": "2026-06-10T12:00:00Z",
  "last_seen": "2026-06-10T12:00:00Z"
}
```

#### `DnsRecordResponse`

```json
{
  "id": "uuid",
  "program_id": "uuid",
  "scope_id": "uuid",
  "host_id": "uuid",
  "subdomain_id": "uuid",
  "subdomain": "api.example.com",
  "record_type": "A",
  "record_value": "93.184.216.34",
  "ttl": 3600,
  "created_at": "2026-06-10T12:00:00Z",
  "updated_at": "2026-06-10T12:00:00Z"
}
```

> `subdomain` is the resolved subdomain **name** (flattened from the `Subdomain`
> relationship at serialization time). `subdomain_id` / `subdomain` are `null`
> for records not tied to a tracked subdomain.

#### `HttpResponseResponse`

```json
{
  "id": "uuid",
  "host_id": "uuid",
  "url": "https://api.example.com",
  "status_code": 200,
  "title": "API Gateway",
  "content_length": 4821,
  "server": "nginx",
  "technologies": ["Nginx:1.20", "React:18.0"],
  "response_time": 42.3
}
```

#### `TechnologyResponse`

```json
{
  "id": "uuid",
  "host_id": "uuid",
  "technology": "Nginx",
  "version": "1.20",
  "confidence": null
}
```

---

## Workers & Tools

### Subdomain Scan Worker

**Celery task**: `workers.subdomain.subdomain_worker.run_subdomain_scan`  
**Triggered by**: `POST /scans/start` with `scan_type=SUBDOMAIN`  
**Scope lock**: `scan_lock:{scope_id}` in Redis (TTL 1800s)

#### 14-step pipeline

```
Step  1–7  Run 7 tools in sequence, raw output → disk
Step  8    Disk-based merge: sort -u across all raw files
Step  9    Bulk upsert subdomains  (50k batch, ON CONFLICT)
Step 10    Bulk insert subdomain_sources (per-tool attribution)
Step 11    Write diff/<timestamp>-new.txt
Step 12    Update ScanRun metrics
Step 13    Discord embed with tool table + new_assets.txt attachment
Step 14    Chain DNS scan (if unique_count > 0) → auto-enqueue run_dns_scan
```

#### Subdomain tools

| Tool | Command | Timeout |
|------|---------|---------|
| **SubfinderRunner** | `subfinder -d TARGET -all -silent` | 300s |
| **AssetfinderRunner** | `assetfinder TARGET` | 300s |
| **KnockpyRunner** | `knockpy -d TARGET --recon --json` | 600s |
| **DnsgenRunner** | `echo TARGET \| dnsgen -` | 300s |
| **ChaosRunner** | `chaos -d TARGET -silent` | 300s |
| **CrtshRunner** | `python3 crtsh.py -r -d TARGET` | 120s |
| **FindomainRunner** | `findomain -t TARGET -q` | 300s |

---

### DNS Scan Worker *(Phase 4)*

**Celery task**: `workers.dns.dns_worker.run_dns_scan`  
**Triggered by**: Auto-chained from SubdomainScanWorker, or `POST /scans/start` with `scan_type=DNS`

#### 8-step pipeline

```
Step 1   Load all subdomains for scope from DB (streaming, 10k batches)
Step 2   Run dnsx (A + AAAA + CNAME + MX + TXT + NS, JSON output)
         Write raw → storage/programs/{pid}/scopes/{sid}/dns/raw/dnsx.json
Step 3   Bulk upsert Asset rows  (type=HOST)
Step 4   Bulk upsert Host rows   (ON CONFLICT scope_id, host)
Step 5   Bulk upsert DnsRecord rows (10k batches)
Step 6   Write processed → dns/processed/resolved.txt
Step 7   Update ScanRun metrics (dnsx_count, resolved_count, new_hosts_count)
Step 8   Discord embed + chain HTTP scan (if resolved_count > 0)
```

#### DNS tools

| Tool | Command | Timeout |
|------|---------|---------|
| **DnsxRunner** | `dnsx -l hosts.txt -a -aaaa -cname -mx -txt -ns -resp -json -t 100` | 900s |

---

### HTTP Scan Worker *(Phase 4)*

**Celery task**: `workers.http.http_worker.run_http_scan`  
**Triggered by**: Auto-chained from DnsScanWorker, or `POST /scans/start` with `scan_type=HTTP`

#### 7-step pipeline

```
Step 1   Load all resolved hosts for scope from DB (streaming, 10k batches)
Step 2   Run httpx (status-code, title, content-length, ip, server,
                    tech-detect, cdn, response-time, JSON output)
         Write raw → storage/programs/{pid}/scopes/{sid}/http/raw/httpx.json
Step 3   UPDATE host rows with HTTP metadata (scheme, port, status_code, …)
Step 4   Bulk upsert HttpResponse rows (5k batches, ON CONFLICT host_id, url)
Step 5   Upsert Technology rows (gen_random_uuid(), ON CONFLICT DO NOTHING)
Step 6   Write processed → http/processed/live.txt
Step 7   Update ScanRun metrics + Discord embed
```

#### HTTP tools

| Tool | Command | Timeout |
|------|---------|---------|
| **HttpxRunner** | `httpx -l hosts.txt -json -silent -title -status-code -content-length -ip -server -tech-detect -cdn -response-time -threads 100` | 900s |

---

### Discord Notifier Worker

| Function | Trigger | Embed content |
|----------|---------|---------------|
| `send_scan_complete_notification` | After subdomain scan | Per-tool raw/in-scope counts, top 10 new subdomains, file attachment |
| `send_dns_scan_notification` | After DNS scan | Input count, resolved count, new/existing hosts, DNS records inserted |
| `send_http_scan_notification` | After HTTP scan | Live hosts, responses saved, technologies found, status-code distribution |

All notification functions are **silent on error** — they never raise.

---

### Scan Scheduler

**Schedule**: Every 5 minutes  
**Purpose**: Heartbeat for re-queuing stuck pending scans.

---

## Scan Pipeline & Orchestration

Starting a single `SUBDOMAIN` scan triggers the full pipeline automatically:

```
POST /scans/start  {scan_type: "SUBDOMAIN"}
        │
        ▼
SubdomainScanWorker
        │  unique_count > 0
        ▼
DnsScanWorker           (countdown 2s)
        │  resolved_count > 0
        ▼
HttpScanWorker          (countdown 2s)
```

You can also start any phase manually:

```bash
# Start DNS scan directly (requires subdomains already in DB)
POST /scans/start  {"program_id": "...", "scope_id": "...", "scan_type": "DNS"}

# Start HTTP scan directly (requires hosts already in DB)
POST /scans/start  {"program_id": "...", "scope_id": "...", "scan_type": "HTTP"}
```

---

## Storage Layout

```
storage/
├── programs/                          ← UUID-keyed (Phase 4, canonical)
│   └── {program_id}/
│       └── scopes/
│           └── {scope_id}/
│               ├── subdomains/
│               │   ├── raw/           ← subfinder.txt, assetfinder.txt, …
│               │   └── processed/     ← subdomains.txt (merged+deduped)
│               ├── dns/
│               │   ├── raw/           ← dnsx.json
│               │   └── processed/     ← resolved.txt
│               ├── http/
│               │   ├── raw/           ← httpx.json
│               │   └── processed/     ← live.txt
│               ├── diff/              ← <timestamp>-new.txt (new subdomains)
│               ├── logs/
│               ├── screenshots/
│               └── reports/
│
└── projects/                          ← Legacy name-keyed (Phase 3 artifacts)
    └── <program_slug>/
        └── scopes/
            └── <scope_target>/
                └── …
```

Old Phase 3 artifacts remain accessible under `storage/projects/`. Call `StorageService.migrate_legacy(program_id, scope_id, program_name, scope_target)` to copy them into the UUID tree.

---

## Discord Notifications

### Subdomain Scan Complete

```
🆕 42 New Asset(s) Found!

Program: AcmeCorp
Scope:   `example.com`

Metrics:
  Subfinder       320 raw       310 in-scope
  Assetfinder     180 raw       170 in-scope
  …
  Merged (raw)    900
  Unique          860
  New assets       42
  Existing        818

Top 10 New Subdomains:
  admin.example.com
  api.example.com
  …

[Attachment: new_assets_sample.txt]
```

### DNS Scan Complete

```
🌐 38 New Host(s) Resolved!

Program: AcmeCorp
Scope:   `example.com`

Metrics:
  Subdomains resolved     860
  Hosts resolved          420
  New hosts                38
  Existing hosts          382
  DNS records inserted   1240
```

### HTTP Scan Complete

```
💻 310 Live Host(s) Found!

Program: AcmeCorp
Scope:   `example.com`

Metrics:
  Hosts probed            420
  Live hosts              310
  HTTP responses saved    310
  Technologies found       94

Status Distribution:
  200: 240
  301: 45
  403: 18
  404: 7
```

---

## Environment Variables

```env
# Database
DB_DRIVER=postgresql
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=
POSTGRES_DB=recon

# Redis (Celery broker + scope locks)
REDIS_URL=redis://localhost:6379/0

# CORS (comma-separated allowed origins)
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

# Discord notifications (optional)
DISCORD_WEBHOOK_URL=https://discordapp.com/api/webhooks/...
```

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run database migrations
alembic upgrade head

# 3. Start the FastAPI server
uvicorn backend.main:app --reload --port 8000

# 4. Start the Celery worker (separate terminal)
celery -A backend.celery_app worker --loglevel=info --concurrency=4

# 5. Start the Celery beat scheduler (separate terminal)
celery -A backend.celery_app beat --loglevel=info
```

### Trigger the full pipeline

```bash
# 1. Create a program
curl -s -X POST http://localhost:8000/programs \
  -H "Content-Type: application/json" \
  -d '{"name": "AcmeCorp", "platform": "HackerOne"}' | jq .

# 2. Add a scope
curl -s -X POST http://localhost:8000/scopes \
  -H "Content-Type: application/json" \
  -d '{"program_id": "<PROGRAM_ID>", "target": "acmecorp.com", "scope_type": "ROOT_DOMAIN"}' | jq .

# 3. Start the full pipeline (auto-chains DNS → HTTP)
curl -s -X POST http://localhost:8000/scans/start \
  -H "Content-Type: application/json" \
  -d '{"program_id": "<PROGRAM_ID>", "scope_id": "<SCOPE_ID>", "scan_type": "SUBDOMAIN"}' | jq .

# 4. Poll status
curl -s http://localhost:8000/scans/<SCAN_ID> | jq .status

# 5. View resolved hosts
curl -s "http://localhost:8000/scopes/<SCOPE_ID>/hosts?live_only=true" | jq .

# 6. View DNS records
curl -s "http://localhost:8000/scopes/<SCOPE_ID>/dns-records?record_type=A" | jq .

# 7. View HTTP responses
curl -s "http://localhost:8000/scopes/<SCOPE_ID>/http-responses" | jq .

# 8. View detected technologies
curl -s "http://localhost:8000/scopes/<SCOPE_ID>/technologies" | jq .

# 9. Full program stats
curl -s "http://localhost:8000/programs/<PROGRAM_ID>/stats" | jq .
```

---

## Running Tests

```bash
# Unit tests only (no DB/Redis required) — runs in < 1 second
pytest -m "not integration" tests/test_phase4_e2e.py -v

# Full integration tests (requires live PostgreSQL + Redis)
pytest -m integration tests/test_phase4_e2e.py -v

# All tests
pytest tests/ -v
```
