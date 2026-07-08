# Reconion — Recon Automation Platform

An end-to-end reconnaissance automation platform. It orchestrates a suite of
open-source security tools (subdomain enumeration, HTTP probing, crawling, JS
analysis, parameter discovery, and vulnerability scanning) behind a FastAPI +
Celery backend, persists results in PostgreSQL, and exposes a React dashboard.

## Architecture

| Layer          | Stack                                             |
|----------------|---------------------------------------------------|
| Frontend       | React 19 + React Router + Vite                    |
| Backend API    | FastAPI + Uvicorn                                 |
| Task queue     | Celery (worker + beat scheduler)                  |
| Broker/result  | Redis                                             |
| Database       | PostgreSQL (SQLAlchemy ORM + Alembic migrations)  |
| Recon engine   | Go + Python CLI tools (see below)                 |

---

## Prerequisites

Install the language runtimes and infrastructure services first.

```bash
# Debian / Ubuntu
sudo apt update
sudo apt install -y python3 python3-venv python3-pip \
                    golang-go git curl unzip \
                    postgresql redis-server

# Node.js 20+ (for the frontend) — via nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
nvm install 20
```

Requirements:
- **Python** 3.12+ (project venv was built with 3.14)
- **Go** 1.21+ (needed to install the Go-based recon tools)
- **Node.js** 20+ / **npm**
- **PostgreSQL** 14+
- **Redis** 6+

---

## 1. Infrastructure services

### PostgreSQL

```bash
sudo systemctl enable --now postgresql

# Create the database and user (matches backend/.env defaults)
sudo -u postgres psql <<'SQL'
CREATE USER reconuser WITH PASSWORD 'change-me';
CREATE DATABASE recon OWNER reconuser;
GRANT ALL PRIVILEGES ON DATABASE recon TO reconuser;
SQL
```

### Redis

```bash
sudo systemctl enable --now redis-server
redis-cli ping   # -> PONG
```

---

## 2. Backend (Python)

```bash
cd backend                       # or run from repo root, adjust paths

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

# Curated dependency set (what the platform imports):
pip install -r ../requirements.txt
# ...or the full frozen environment:
# pip install -r ../requirements.full.txt

# Apply database migrations
alembic upgrade head
```

Create/adjust `backend/.env`:

```dotenv
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=recon
POSTGRES_USER=reconuser
POSTGRES_PASSWORD=change-me
REDIS_URL=redis://localhost:6379/0
```

---

## 3. Recon tools

The backend shells out to a set of external CLI binaries. The Go tools are
committed under [`tools/bin/`](tools/bin/), and the Python tools live under
[`tools/`](tools/). Put `tools/bin` on your `PATH` (or reinstall as below).

```bash
export PATH="$PWD/tools/bin:$PATH"
```

### Go-based tools

Install with `go install` (binaries land in `$(go env GOPATH)/bin` — add it to `PATH`):

```bash
export PATH="$PATH:$(go env GOPATH)/bin"

# Subdomain enumeration
go install github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest
go install github.com/tomnomnom/assetfinder@latest
go install github.com/projectdiscovery/chaos-client/cmd/chaos@latest

# DNS resolution / permutation
go install github.com/projectdiscovery/dnsx/cmd/dnsx@latest

# HTTP probing
go install github.com/projectdiscovery/httpx/cmd/httpx@latest

# Crawling / URL collection
go install github.com/projectdiscovery/katana/cmd/katana@latest
go install github.com/hakluke/hakrawler@latest
go install github.com/lc/gau/v2/cmd/gau@latest
go install github.com/tomnomnom/waybackurls@latest

# JavaScript analysis
go install github.com/lc/subjs@latest
go install github.com/BishopFox/jsluice/cmd/jsluice@latest
go install github.com/MrEmpy/mantra@latest

# Vulnerability scanning
go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest
```

**findomain** (subdomain enumeration) ships as a release binary:

```bash
curl -L https://github.com/Findomain/Findomain/releases/latest/download/findomain-linux.zip -o findomain.zip
unzip findomain.zip && chmod +x findomain
sudo mv findomain /usr/local/bin/
```

### Python-based tools

These install into the backend venv:

```bash
# With the venv active:
pip install arjun==2.2.7            # parameter discovery
pip install dnsgen==1.0.4           # DNS permutation generation
pip install knock-subdomains==9.0.0 # knockpy — subdomain enumeration
pip install git+https://github.com/devanshbatham/ParamSpider.git  # paramspider
```

Vendored Python tools (already in-tree under [`tools/`](tools/)):

```bash
# SecretFinder deps:
pip install -r tools/SecretFinder/requirements.txt

# LinkFinder / SecretFinder / xnLinkFinder run directly:
python3 tools/LinkFinder/linkfinder.py -h
python3 tools/SecretFinder/SecretFinder.py -h
python3 tools/xnLinkFinder/xnLinkFinder -h
```

### Nuclei templates

Templates are committed under [`nuclei-templates/`](nuclei-templates/). To refresh:

```bash
nuclei -update-templates
```

---

## 4. Frontend

```bash
cd frontend
npm install
```

---

## Running the platform

Two helper scripts bring everything up:

```bash
# Backend: Redis check + Celery worker + Celery beat + FastAPI (port 8000)
./backend_start.sh

# Frontend: Vite dev server (port 5173)
./frontend_start.sh
# Production preview:  MODE=preview ./frontend_start.sh
```

- API:   http://localhost:8000  (Swagger docs at `/docs`)
- UI:    http://localhost:5173
- Logs:  [`logs/`](logs/) — `backend.log`, `celery_worker.log`, `celery_beat.log`, `redis.log`

---

## Tool reference

| Tool          | Type   | Purpose                              | Install |
|---------------|--------|--------------------------------------|---------|
| subfinder     | Go     | Passive subdomain enumeration        | `go install` |
| assetfinder   | Go     | Subdomain discovery                  | `go install` |
| chaos         | Go     | ProjectDiscovery Chaos dataset       | `go install` |
| findomain     | Go     | Subdomain enumeration                | release binary |
| knockpy       | Python | Subdomain enumeration                | `pip install knock-subdomains` |
| dnsx          | Go     | DNS toolkit / resolution             | `go install` |
| dnsgen        | Python | DNS wordlist permutation             | `pip install dnsgen` |
| httpx         | Go     | HTTP probing / tech detection        | `go install` |
| katana        | Go     | Crawler                              | `go install` |
| hakrawler     | Go     | Crawler                              | `go install` |
| gau           | Go     | Fetch known URLs                     | `go install` |
| waybackurls   | Go     | Wayback Machine URLs                 | `go install` |
| subjs         | Go     | Extract JS file URLs                 | `go install` |
| jsluice       | Go     | Extract URLs/secrets from JS         | `go install` |
| mantra        | Go     | Find secrets in JS                   | `go install` |
| LinkFinder    | Python | Endpoints in JS files                | vendored |
| xnLinkFinder  | Python | Endpoints/params in JS               | vendored |
| SecretFinder  | Python | Secrets in JS files                  | vendored |
| arjun         | Python | HTTP parameter discovery             | `pip install arjun` |
| paramspider   | Python | Parameter mining (archives)          | `pip install` from git |
| nuclei        | Go     | Template-based vulnerability scanner | `go install` |
