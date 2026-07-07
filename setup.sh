#!/usr/bin/env bash
#
# setup.sh — one-shot environment setup for the Recon Automation Platform.
#
# Installs everything the platform needs to run:
#   1. System packages   (Python, Redis, PostgreSQL, Go, Node/npm, build deps)
#   2. Python virtualenv (backend/.venv) + all pip requirements
#   3. Python recon tools (arjun, paramspider, knockpy, dnsgen, LinkFinder/
#                          SecretFinder deps) into the venv
#   4. Go recon tools     (rebuilt into tools/bin only if missing/broken)
#   5. PostgreSQL database (creates role + DB) and runs Alembic migrations
#   6. Frontend npm dependencies
#
# Idempotent: safe to re-run. Steps that are already satisfied are skipped.
#
# Usage:
#   ./setup.sh                    # full setup
#   SKIP_SYSTEM=1 ./setup.sh      # skip apt system-package install (no sudo)
#   SKIP_GO=1 ./setup.sh          # don't (re)build Go tools
#   SKIP_FRONTEND=1 ./setup.sh    # skip npm install
#   SKIP_DB=1 ./setup.sh          # skip Postgres role/db + migrations
#
# After it finishes:
#   ./backend_start.sh   # API + Celery worker/beat + Redis
#   ./frontend_start.sh  # Vite dev server

set -euo pipefail

# --- Paths --------------------------------------------------------------------
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
TOOLS_DIR="$ROOT_DIR/tools"
TOOLS_BIN="$TOOLS_DIR/bin"
VENV_DIR="$BACKEND_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python"
REQ_FILE="$ROOT_DIR/requirements.txt"

# --- Pretty output ------------------------------------------------------------
c_reset=$'\033[0m'; c_blue=$'\033[1;34m'; c_green=$'\033[1;32m'
c_yellow=$'\033[1;33m'; c_red=$'\033[1;31m'
step() { echo; echo "${c_blue}==> $*${c_reset}"; }
ok()   { echo "${c_green}  ✓ $*${c_reset}"; }
warn() { echo "${c_yellow}  ! $*${c_reset}"; }
die()  { echo "${c_red}ERROR: $*${c_reset}" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- Config knobs -------------------------------------------------------------
SKIP_SYSTEM="${SKIP_SYSTEM:-0}"
SKIP_GO="${SKIP_GO:-0}"
SKIP_FRONTEND="${SKIP_FRONTEND:-0}"
SKIP_DB="${SKIP_DB:-0}"

echo "${c_blue}Recon Automation Platform — setup${c_reset}"
echo "Repo: $ROOT_DIR"

# =============================================================================
# 1. System packages
# =============================================================================
step "1/6  System packages"
if [[ "$SKIP_SYSTEM" == "1" ]]; then
  warn "SKIP_SYSTEM=1 — skipping apt install (assuming deps are present)."
elif have apt-get; then
  SUDO=""
  [[ "$(id -u)" -ne 0 ]] && SUDO="sudo"
  echo "  Installing system packages (needs sudo)..."
  $SUDO apt-get update -y
  $SUDO apt-get install -y \
    python3 python3-venv python3-dev python3-pip pipx \
    build-essential libpq-dev libssl-dev libffi-dev \
    redis-server \
    postgresql postgresql-contrib \
    golang-go \
    nodejs npm \
    git curl unzip
  ok "System packages installed."
else
  warn "apt-get not found — install these manually for your distro:"
  warn "  python3(+venv,+dev), redis-server, postgresql, golang-go, nodejs/npm,"
  warn "  build-essential, libpq-dev, libssl-dev, libffi-dev, git, curl, unzip"
fi

have python3 || die "python3 is required but not found."
PY_VER="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"
ok "Using system python3 ($PY_VER)"

# =============================================================================
# 2. Python virtualenv + pip requirements
# =============================================================================
step "2/6  Python virtualenv (backend/.venv)"
if [[ -x "$VENV_PY" ]]; then
  ok "venv already exists at $VENV_DIR"
else
  echo "  Creating virtualenv..."
  python3 -m venv "$VENV_DIR"
  ok "Created $VENV_DIR"
fi

echo "  Upgrading pip / setuptools / wheel..."
"$VENV_PY" -m pip install --upgrade pip setuptools wheel >/dev/null
ok "pip toolchain up to date"

if [[ -f "$REQ_FILE" ]]; then
  echo "  Installing pip requirements..."
  "$VENV_PY" -m pip install -r "$REQ_FILE"
  ok "requirements.txt installed"
else
  die "requirements.txt not found at $REQ_FILE"
fi

# =============================================================================
# 3. Python-based recon tools (into the venv)
# =============================================================================
step "3/6  Python recon tools"
# arjun is pinned in requirements.txt; add the rest of the Python CLI tools and
# library deps used by the bundled Python tools (LinkFinder / SecretFinder).
echo "  Installing paramspider, knockpy, dnsgen, LinkFinder/SecretFinder deps..."
"$VENV_PY" -m pip install \
  paramspider \
  knock-subdomains \
  dnsgen \
  requests requests_file jsbeautifier lxml
ok "Python recon tools installed into venv"

# xnLinkFinder / LinkFinder / SecretFinder ship as source under tools/ and are
# invoked via the venv interpreter; their deps (above) are all that's needed.
for t in LinkFinder SecretFinder xnLinkFinder; do
  [[ -d "$TOOLS_DIR/$t" ]] && ok "bundled: tools/$t" || warn "missing bundled tool dir: tools/$t"
done

# =============================================================================
# 4. Go-based recon tools (tools/bin)
# =============================================================================
step "4/6  Go recon tools (tools/bin)"
mkdir -p "$TOOLS_BIN"

# Map of bundled-binary-name -> `go install` module path (for rebuilding any
# that are missing). Bundled binaries in tools/bin are used as-is if present.
declare -A GO_TOOLS=(
  [subfinder]="github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest"
  [httpx]="github.com/projectdiscovery/httpx/cmd/httpx@latest"
  [dnsx]="github.com/projectdiscovery/dnsx/cmd/dnsx@latest"
  [katana]="github.com/projectdiscovery/katana/cmd/katana@latest"
  [nuclei]="github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest"
  [chaos]="github.com/projectdiscovery/chaos-client/cmd/chaos@latest"
  [assetfinder]="github.com/tomnomnom/assetfinder@latest"
  [gau]="github.com/lc/gau/v2/cmd/gau@latest"
  [waybackurls]="github.com/tomnomnom/waybackurls@latest"
  [hakrawler]="github.com/hakluke/hakrawler@latest"
  [subjs]="github.com/lc/subjs@latest"
)
# jsluice, findomain, mantra, dnsgen(py) are not covered by go install here —
# they are expected to be present as bundled binaries.

if [[ "$SKIP_GO" == "1" ]]; then
  warn "SKIP_GO=1 — not building Go tools."
elif ! have go; then
  warn "go not found — skipping Go tool build. Existing tools/bin binaries will be used."
else
  export GOBIN="$TOOLS_BIN"
  missing=0
  for name in "${!GO_TOOLS[@]}"; do
    if [[ -x "$TOOLS_BIN/$name" ]]; then
      ok "present: $name"
    else
      warn "building: $name"
      if go install "${GO_TOOLS[$name]}"; then
        ok "built: $name"
      else
        warn "failed to build $name — install manually if needed."
        missing=$((missing+1))
      fi
    fi
  done
  [[ "$missing" -eq 0 ]] && ok "All Go tools present." || warn "$missing Go tool(s) could not be built."
fi

# Report any bundled-only binaries that are missing (not auto-built above).
for name in jsluice findomain mantra knockpy paramspider arjun dnsgen; do
  [[ -e "$TOOLS_BIN/$name" ]] || warn "tools/bin/$name missing (bundled tool)."
done

# nuclei-templates
if [[ -d "$ROOT_DIR/nuclei-templates" ]]; then
  ok "nuclei-templates present"
else
  warn "nuclei-templates/ missing — run 'nuclei -update-templates' if you use nuclei."
fi

# =============================================================================
# 5. PostgreSQL database + Alembic migrations
# =============================================================================
step "5/6  Database (PostgreSQL) + migrations"

# Load DB settings from backend/.env if present (keys only; defaults otherwise).
DB_USER_DEFAULT="postgres"; DB_NAME_DEFAULT="recon"
PGUSER_ENV="$(grep -E '^POSTGRES_USER=' "$BACKEND_DIR/.env" 2>/dev/null | cut -d= -f2- || true)"
PGDB_ENV="$(grep -E '^POSTGRES_DB=' "$BACKEND_DIR/.env" 2>/dev/null | cut -d= -f2- || true)"
PG_USER="${PGUSER_ENV:-$DB_USER_DEFAULT}"
PG_DB="${PGDB_ENV:-$DB_NAME_DEFAULT}"

if [[ ! -f "$BACKEND_DIR/.env" ]]; then
  warn "backend/.env not found — create it with POSTGRES_*/REDIS_URL before starting."
  warn "Required keys: POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER,"
  warn "               POSTGRES_PASSWORD, REDIS_URL, ENV, DISCORD_WEBHOOK_URL"
fi

if [[ "$SKIP_DB" == "1" ]]; then
  warn "SKIP_DB=1 — skipping database creation and migrations."
else
  # Start Postgres if we can.
  if have pg_isready && ! pg_isready -q 2>/dev/null; then
    warn "PostgreSQL not accepting connections — attempting to start service..."
    if have systemctl; then sudo systemctl start postgresql 2>/dev/null || \
      sudo service postgresql start 2>/dev/null || true; fi
  fi

  if have psql && pg_isready -q 2>/dev/null; then
    # Create the database if it doesn't exist (uses local peer auth as postgres).
    if sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$PG_DB'" 2>/dev/null | grep -q 1; then
      ok "database '$PG_DB' already exists"
    else
      echo "  Creating database '$PG_DB'..."
      sudo -u postgres createdb "$PG_DB" 2>/dev/null \
        && ok "created database '$PG_DB'" \
        || warn "could not create '$PG_DB' automatically — create it manually."
    fi

    # Run Alembic migrations from the backend dir (prepend_sys_path='.').
    echo "  Running Alembic migrations..."
    if (cd "$BACKEND_DIR" && "$VENV_PY" -m alembic upgrade head); then
      ok "migrations applied (alembic upgrade head)"
    else
      warn "alembic upgrade failed — check backend/.env DB credentials and connectivity."
    fi
  else
    warn "psql/PostgreSQL not ready — skipping DB create + migrations."
    warn "After Postgres is up, run:  cd backend && ../backend/.venv/bin/python -m alembic upgrade head"
  fi
fi

# =============================================================================
# 6. Frontend dependencies
# =============================================================================
step "6/6  Frontend (npm)"
if [[ "$SKIP_FRONTEND" == "1" ]]; then
  warn "SKIP_FRONTEND=1 — skipping npm install."
elif [[ ! -d "$FRONTEND_DIR" ]]; then
  warn "frontend/ not found — skipping."
elif ! have npm; then
  warn "npm not found — install Node.js, then run 'npm install' in frontend/."
else
  echo "  Installing frontend dependencies..."
  (cd "$FRONTEND_DIR" && npm install)
  ok "frontend dependencies installed"
fi

# =============================================================================
# Done
# =============================================================================
echo
echo "${c_green}=============================================${c_reset}"
echo "${c_green} Setup complete.${c_reset}"
echo "${c_green}=============================================${c_reset}"
echo
echo "Next steps:"
echo "  1. Ensure backend/.env has valid POSTGRES_* / REDIS_URL values."
echo "  2. Start the backend :  ./backend_start.sh"
echo "  3. Start the frontend:  ./frontend_start.sh"
echo
echo "Verify recon tools resolve:"
echo "  $VENV_PY -c \"from tools.common.tool_paths import tool_availability; import json; print(json.dumps(tool_availability(), indent=2))\""
