# Recon Pipeline — Phase Reference

Complete reference for every reconnaissance phase in this platform: the tools it
runs, the exact command line, what goes in, what comes out, how results are
merged/deduplicated, and where the data lands (files + database).

---

## 1. Architecture in one page

```
FastAPI (backend/main.py)          Celery workers (workers/)         PostgreSQL
      │  POST /scans/start               │                                │
      └──────── enqueue ────────────────►│  one worker per phase          │
                                         │  tool runners in tools/        │
                                         └──── artifacts ───► storage/    │
                                                              └─ raw/processed
```

**Layers**

| Layer | Location | Responsibility |
|---|---|---|
| API | `backend/api/` | REST routes; start scans, read results |
| Services | `backend/services/` | Orchestration, storage paths, scan lifecycle |
| Workers | `workers/` | One Celery task per phase; runs tools, merges, persists |
| Tool runners | `tools/` | Thin wrappers around each binary (`ToolBase` subclasses) |
| Repositories | `repositories/` | Bulk upserts / queries (no ORM row-by-row loops) |
| Models | `database/models/` | SQLAlchemy schema |

**Key invariants**

- **Tool failure is isolated.** One tool erroring never aborts the phase; it is
  recorded as a `FAILED` row in `tool_executions` and the rest continue.
- **One scan per scope at a time**, enforced by a Redis scope lock.
- **Every phase writes raw + processed artifacts** to disk before/while persisting
  to the DB, so results survive a DB problem and are auditable.
- **Bulk upserts only** — `ON CONFLICT` on a natural key, never per-row inserts.
- **Counters are maintained at write time** (`hosts.url_count`, `js_count`,
  `endpoint_count`, `secret_count`, `screenshot_count`) so the API never runs
  `COUNT(*)` per host.
- **Pause/stop** signals are polled at safe boundaries (between tools/batches);
  workers checkpoint into `scan_runs.resume_state`.

---

## 2. Phase chain

Each phase automatically enqueues the next. Starting at any stage runs everything
after it.

```
SUBDOMAIN ──► DNS ──► HTTP ──► CONTENT_DISCOVERY ──► JS_ENDPOINT ──► JS_SECRET

SCREENSHOT  (standalone — run manually after HTTP; does not chain)
```

| ScanType | Celery task | Worker file |
|---|---|---|
| `SUBDOMAIN` | `workers.subdomain.subdomain_worker.run_subdomain_scan` | `workers/subdomain/subdomain_worker.py` |
| `DNS` | `workers.dns.dns_worker.run_dns_scan` | `workers/dns/dns_worker.py` |
| `HTTP` | `workers.http.http_worker.run_http_scan` | `workers/http/http_worker.py` |
| `CONTENT_DISCOVERY` | `workers.url.url_worker.run_url_scan` | `workers/url/url_worker.py` |
| `JS_ENDPOINT` | `workers.js_endpoint_worker.run_js_endpoint_scan` | `workers/js_endpoint_worker.py` |
| `JS_SECRET` | `workers.js_secret_worker.run_js_secret_scan` | `workers/js_secret_worker.py` |
| `SCREENSHOT` | `workers.http.screenshot_worker.run_screenshot_scan` | `workers/http/screenshot_worker.py` |

Start any phase:

```http
POST /scans/start
{ "program_id": "<uuid>", "scope_id": "<uuid>", "scan_type": "SUBDOMAIN" }
```

---

## 3. Storage layout

All artifacts are UUID-keyed so renaming a program/scope never breaks paths.

```
storage/
└── programs/<program_id>/
    └── scopes/<scope_id>/
        ├── subdomains/{raw,processed}/
        ├── dns/{raw,processed}/
        ├── http/{raw,processed}/
        ├── urls/{raw,processed}/
        ├── js/{raw,processed}/
        ├── endpoints/{raw,processed}/
        ├── secrets/{raw,processed}/
        ├── screenshots/            ← gowitness JPEGs (flat)
        ├── diff/                   ← per-run "new since last scan" files
        ├── logs/  reports/
```

- **`raw/`** — untouched per-tool output (one file per tool).
- **`processed/`** — merged, normalized, deduplicated result for the phase.
- **`diff/`** — `YYYY-MM-DDTHH-MM-SS-new.txt`, only newly discovered assets.

Screenshots are served over HTTP by the static mount in `backend/main.py`:

```
GET /storage/programs/<pid>/scopes/<sid>/screenshots/<file>.jpeg
```

---

## 4. Phase 1 — Subdomain enumeration (`SUBDOMAIN`)

**Input:** the scope target (e.g. `example.com`) from the `scopes` table.

**Tools** (run in a thread pool; each isolated):

| Tool | Command | Input | Raw output |
|---|---|---|---|
| subfinder | `subfinder -d <domain> -all -recursive -silent` | domain | `raw/subfinder.txt` |
| assetfinder | `assetfinder <domain>` | domain | `raw/assetfinder.txt` |
| knockpy | `knockpy -d <domain> --recon --json` | domain | `raw/knockpy.txt` (+ `knockpy.json`) |
| dnsgen | `dnsgen -` (domain on **stdin**) | domain | `raw/dnsgen.txt` |
| chaos | `chaos -d <domain> -silent` | domain | `raw/chaos.txt` |
| crt.sh | `crtsh -q <domain>` (retries up to 6×, 5 s apart) | domain | `raw/crtsh.txt` |
| findomain | `findomain -t <domain> -q` | domain | `raw/findomain.txt` |

> knockpy runs in a throwaway temp CWD with `KNOCKPY_DB` redirected so its
> report/DB files never litter the repo. `HOME` is deliberately **not** overridden —
> knockpy reads its API keys from `~/.knockpy/recon_services.json`.

**Compilation**

1. Each tool's output is scope-filtered (`tools/common/scope_filter.py`) — anything
   not under the target domain is dropped. Metrics keep both `*_raw` (all lines)
   and `*_count` (in-scope).
2. All in-scope raw files are merged with a **disk-based `sort -u`** (not in
   memory — handles 100 k+ entries) → `processed/subdomains.txt`.
3. Bulk upsert into `subdomains` `ON CONFLICT (scope_id, subdomain)`.
4. Per-tool attribution rows → `subdomain_sources` (which tool found what).
5. New-only entries → `diff/<timestamp>-new.txt`.
6. `scan_runs` metric columns updated; one Discord embed sent with a
   `new_assets.txt` attachment.

**Tables:** `subdomains`, `subdomain_sources`, `assets`, `tool_executions`, `scan_runs`
**Chains:** → `DNS`

---

## 5. Phase 2 — DNS resolution (`DNS`)

**Input:** all `subdomains` rows for the scope (streamed from DB).

**Tool**

```bash
dnsx -l <subdomains.txt> \
     -a -aaaa -cname -mx -txt -ns \
     -resp -json -silent \
     -retry 2 -t 100 \
     [-r resolver1,resolver2]
```

- **Input:** newline-delimited subdomain list (temp file)
- **Output:** newline-delimited JSON → `dns/raw/dnsx.json`
- Resolved hostnames → `dns/processed/resolved.txt`

**Compilation**

1. Parse each JSON line into a `DnsxRecord` (host + A/AAAA/CNAME/MX/TXT/NS).
2. Bulk-upsert `assets` rows (`type=HOST`) for each resolved host.
3. Bulk-upsert `hosts` `ON CONFLICT (scope_id, host)`.
4. Bulk-upsert `dns_records` `ON CONFLICT (host_id, record_type, record_value)`.
5. Update `scan_runs` (`dnsx_count`, `resolved_count`, `new_hosts_count`) + Discord.

**Tables:** `hosts`, `dns_records`, `assets`
**Chains:** → `HTTP`

---

## 6. Phase 3 — HTTP probing (`HTTP`)

**Input:** all resolved `hosts` for the scope.

**Tool**

```bash
httpx -l <hosts.txt> -json -silent \
      -title -status-code -content-length -ip -server \
      -tech-detect -cdn -response-time \
      -threads 200 -timeout 10 -retries 1 \
      -ports 80,443,8080,8000,8888 -follow-redirects
```

> The wrapper resolves the **projectdiscovery Go binary explicitly**
> (`tools/bin/httpx`, then `~/go/bin/httpx`) — never a bare PATH lookup, because
> `/usr/bin/httpx` is the unrelated Python HTTP client.

- **Output:** `http/raw/httpx.json`; live URLs → `http/processed/live.txt`

**Compilation**

1. Update `hosts` with HTTP metadata in a **single** `UPDATE ... FROM (VALUES ...)`
   statement per batch (scheme, port, ip, status_code, title, content_length,
   response_time, cdn, waf, last_seen).
2. Upsert `http_responses` `ON CONFLICT (host_id, url)` — deduped first, since
   httpx can emit several records per (host,url) across ports/redirects.
3. Upsert `technologies` (`ON CONFLICT DO NOTHING`), splitting `"Name:version"`.
4. Track status-code distribution + `new_live` (hosts live for the first time).

**Tables:** `hosts`, `http_responses`, `technologies`
**Chains:** → `CONTENT_DISCOVERY`

---

## 7. Phase 4 — Content discovery (`CONTENT_DISCOVERY`)

**Input:** live hosts (URLs) + bare hostnames for the scope.

**Tools** (parallel, streamed to disk)

| Tool | Command | Input | Raw output |
|---|---|---|---|
| gau | `gau --threads N --subs --providers wayback,commoncrawl,otx,urlscan` | hosts on **stdin** | `urls/raw/gau.json` |
| waybackurls | `waybackurls` | hosts on **stdin** | `urls/raw/waybackurls.json` |
| katana | `katana -list <f> -jsonl -silent -depth D -concurrency C -parallelism P -rate-limit R -js-crawl -known-files all -no-color` | URL list file | `urls/raw/katana.json` |
| hakrawler | `hakrawler -d D -t T -u -insecure` | hosts on **stdin** | `urls/raw/hakrawler.json` |
| subjs | `subjs -i <f> -c C -t T` | URL list file | `js/raw/subjs.json` |

JS files surfaced by crawlers are split out to `js/raw/katana_js.json` and
`js/raw/hakrawler_js.json`.

**Compilation**

1. Merge → **normalize** → deduplicate across all tools, tracking which tools
   found each URL. Merged artifacts: `urls/raw/merged_urls.json`,
   `js/raw/merged_js.json`.
2. Bulk-upsert `urls` and `js_files` (JS is separated from ordinary URLs).
3. Bulk-insert per-tool attribution → `url_sources`, `js_file_sources`.
4. Increment `hosts.url_count` / `hosts.js_count` — **new rows only**.

**Tables:** `urls`, `url_sources`, `js_files`, `js_file_sources`
**Chains:** → `JS_ENDPOINT`

---

## 8. Phase 5 — JS endpoint discovery (`JS_ENDPOINT`)

**Input:** `js_files` rows (streamed in batches, constant memory).

Per batch: download the JS to a temp dir → run extractors in parallel → merge →
**delete the downloaded JS** (guaranteed in `finally`, even on error).

| Extractor | Command | Input |
|---|---|---|
| LinkFinder | `<venv python> linkfinder.py -i <file.js> -o cli` | local JS file |
| XNLinkFinder | `xnLinkFinder.py -i <dir> -o <out> -op <params> -sf <scope> -nb` (run under a PTY) | directory of JS |
| JSluice | `jsluice urls -c <N> <file.js> ...` | local JS files (AST-based) |

> LinkFinder is invoked with `sys.executable` (the venv interpreter), not bare
> `python3` — under systemd the system interpreter lacks `jsbeautifier` and would
> silently yield zero endpoints.

**Compilation**

1. Merge raw hits → **resolve relative paths against the JS file's URL** →
   normalize → dedupe into fully-qualified absolute URLs.
2. Bulk-upsert `endpoints`; on conflict the `discovery_tools` JSON array is
   **unioned**, so one endpoint records every tool that found it.
3. Per-tool rows → `endpoint_sources`.
4. Increment `hosts.endpoint_count` / `subdomains.endpoint_count` (new only).
5. Merged artifact → `endpoints/processed/merged_endpoints.txt`.

**Tables:** `endpoints`, `endpoint_sources`
**Chains:** → `JS_SECRET`

---

## 9. Phase 6 — JS secret discovery (`JS_SECRET`)

**Input:** the full JS surface — `js_files` plus URLs/endpoints classified as JS
(deduplicated), streamed in keyset batches.

| Scanner | Command | Input |
|---|---|---|
| SecretFinder | `python3 SecretFinder.py -i <file.js> -o cli` | local JS file |
| Mantra | `mantra -s -t <threads>` | JS **URLs** on stdin |
| Nuclei | `nuclei -t http/exposures -jsonl -silent -nc -c C -rate-limit R -bulk-size B -disable-update-check` | JS **URLs** on stdin |

> Nuclei is restricted to `http/exposures/` templates **only** — this is secret
> discovery, never vulnerability scanning.

**Compilation**

1. Classify each hit into a `SecretType` (AWS key, JWT, Stripe, private key, …),
   normalize, then compute a **fingerprint** = stable hash of
   `(secret_type, normalized_secret)`.
2. Upsert `js_secrets` `ON CONFLICT (scope_id, fingerprint)` → the same key found
   in many files/tools collapses into one row with a **unioned** `discovery_tools`.
3. Per-tool provenance → `js_secret_sources`.
4. Increment `hosts.secret_count` / `subdomains.secret_count` (new only).
5. Merged artifact → `secrets/processed/merged_secrets.json`; Discord alert per
   newly discovered secret.

**Secrets are stored unmasked** — analysts must be able to verify and report them.

**Tables:** `js_secrets`, `js_secret_sources`
**Chains:** end of chain.

---

## 10. Phase 7 — Screenshots (`SCREENSHOT`, standalone)

Run manually after HTTP probing. It does **not** chain another phase.

**Input:** all live `hosts` (those with a `status_code`), one URL built per host
from `scheme` + `host` + `port`.

**Tool**

```bash
gowitness scan file \
  -f <screenshots/gowitness-input.txt> \
  -s storage/programs/<pid>/scopes/<sid>/screenshots \
  --screenshot-format jpeg \
  --write-jsonl --write-jsonl-file <screenshots/gowitness.jsonl> \
  --threads 15 --timeout 30
```

Implementation notes (`tools/http/gowitness_runner.py`):

- The input list is written **beside the artifacts**, not in `/tmp` — some
  worker/container setups run gowitness under a different mount namespace or user
  and cannot read a transient `/tmp` file.
- The JSONL file is **deleted before each run**; gowitness appends, so a rerun
  would otherwise ingest stale captures from an earlier scan.
- A non-zero exit surfaces both stdout and stderr (gowitness prints the real error
  on stdout and usage text on stderr).

**Output**

- Images: `screenshots/<scheme>---<host>-<port>.jpeg`
- Results: `screenshots/gowitness.jsonl` → `url`, `final_url`, `title`,
  `response_code`, `file_name`, `failed`, `failed_reason`

**Compilation**

1. gowitness expands each input URL into `:80`/`:443` variants and reports
   `scheme://host:port`, so records are mapped back to a host **by bare hostname**,
   not by exact URL string.
2. Upsert `screenshots` `ON CONFLICT (host_id, url)`; `file_path` is stored
   **relative to the storage root** so it is mount-location independent.
3. Set `hosts.screenshot_path` (preferring the **https** capture as the canonical
   thumbnail) and refresh `hosts.screenshot_count`.

**Tables:** `screenshots`, `hosts`

---

## 11. Data model summary

| Table | Natural key (upsert) | Written by |
|---|---|---|
| `subdomains` | `(scope_id, subdomain)` | Phase 1 |
| `subdomain_sources` | `(subdomain_id, tool_name, scan_run_id)` | Phase 1 |
| `hosts` | `(scope_id, host)` | Phase 2 (+3,4,5,6,7 counters) |
| `dns_records` | `(host_id, record_type, record_value)` | Phase 2 |
| `http_responses` | `(host_id, url)` | Phase 3 |
| `technologies` | no unique constraint — `ON CONFLICT DO NOTHING` | Phase 3 |
| `urls` | `(scope_id, normalized_url)` | Phase 4 |
| `js_files` | `(scope_id, url)` | Phase 4 |
| `url_sources` / `js_file_sources` | `(parent_id, tool_name)` | Phase 4 |
| `endpoints` | `(scope_id, normalized_url)` | Phase 5 |
| `endpoint_sources` | `(endpoint_id, tool_name)` | Phase 5 |
| `js_secrets` | `(scope_id, fingerprint)` | Phase 6 |
| `js_secret_sources` | `(secret_id, tool_name)` | Phase 6 |
| `screenshots` | `(host_id, url)` | Phase 7 |
| `scan_runs` / `tool_executions` | — | every phase |

`tool_executions` records one row per tool invocation: command, status,
`raw_records_found`, `records_found`, timings, and the error message on failure —
this is the audit trail for "which tool actually produced what".

---

## 12. Reading results via the API

| Endpoint | Returns |
|---|---|
| `GET /scopes/{id}/subdomains` | discovered subdomains |
| `GET /scopes/{id}/hosts?live_only=true` | resolved hosts (+ all counters) |
| `GET /scopes/{id}/dns-records` | DNS records |
| `GET /scopes/{id}/http-responses` | HTTP responses |
| `GET /scopes/{id}/technologies` | detected technologies |
| `GET /scopes/{id}/urls` | discovered URLs (paginated/searchable) |
| `GET /scopes/{id}/js-files` | discovered JS files |
| `GET /scopes/{id}/endpoints` | JS-derived endpoint inventory (paginated) |
| `GET /scopes/{id}/endpoint-stats` · `/endpoint-hosts` | endpoint aggregates / host filter list |
| `GET /scopes/{id}/secrets` | discovered secrets (also by program / subdomain / host / js-file) |
| `GET /scopes/{id}/secret-stats` | secret aggregates by type & severity |
| `GET /scopes/{id}/screenshots` | screenshot records |
| `GET /scopes/{id}/stats` | scope summary counters |
| `GET /scans/{id}/report` | per-tool execution report for a run |
| `GET /storage/<relative_path>` | the artifact file itself (e.g. a screenshot) |

Scan control: `POST /scans/start`, and `POST /scans/{id}/pause` · `/resume` · `/stop`.

The **Live Domains** page consumes `hosts`, `technologies`, `http-responses`,
`dns-records` and `screenshots`, and renders a per-domain detail slide-over with
the screenshot plus every counter, navigable with Prev/Next (or ←/→).

---

## 13. Tool inventory

Binaries resolve **bundled-first** (`tools/bin/`), then `~/go/bin`, then the venv
bin, then `PATH` — see `tools/common/tool_paths.py`. On worker boot, availability
of every expected binary is logged; a missing tool is skipped (its step is marked
failed), it never blocks a scan.

| Phase | Tools |
|---|---|
| Subdomain | subfinder, assetfinder, knockpy, dnsgen, chaos, crtsh, findomain |
| DNS | dnsx |
| HTTP | httpx |
| Content discovery | gau, waybackurls, katana, hakrawler, subjs |
| JS endpoints | LinkFinder, xnLinkFinder, jsluice |
| JS secrets | SecretFinder, mantra, nuclei (`http/exposures` only) |
| Screenshots | gowitness |

Health check for any wrapper:

```python
from tools.http.gowitness_runner import GowitnessRunner
GowitnessRunner().health_check()
# {'tool': 'gowitness', 'available': True, 'binary': '.../tools/bin/gowitness', ...}
```

---

## 14. Operating notes

- **Scope lock:** one scan per scope; starting a second returns HTTP 409.
- **Pause/resume/stop:** `POST /scans/{id}/pause|resume|stop`. Workers poll the
  Redis control signal at safe boundaries and checkpoint into
  `scan_runs.resume_state`.
- **Logs:** per-worker at `backend/logs/workers/<worker>.log`; API at
  `backend/logs/app.log`.
- **Migrations:** `python -m alembic upgrade head` from `backend/`.
- **Deleting** a program/scope removes its whole artifact tree; storage errors are
  logged but never block the DB delete.
