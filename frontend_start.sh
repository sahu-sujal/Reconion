#!/usr/bin/env bash
#
# frontend_start.sh — start the Recon Platform frontend (Vite dev server).
#
# Installs npm dependencies on first run (or when node_modules is missing),
# then launches the Vite dev server.
#
# Usage:
#   ./frontend_start.sh                 # dev server (default)
#   MODE=preview ./frontend_start.sh    # build + serve the production bundle
#
# Env overrides:
#   HOST  — interface to bind (default: localhost)
#   PORT  — port to serve on   (default: 5173)
#   MODE  — "dev" (default) or "preview"

set -euo pipefail

# --- Paths --------------------------------------------------------------------
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"

HOST="${HOST:-localhost}"
PORT="${PORT:-5173}"
MODE="${MODE:-dev}"

# --- Sanity checks ------------------------------------------------------------
if [[ ! -d "$FRONTEND_DIR" ]]; then
  echo "ERROR: frontend directory not found at $FRONTEND_DIR" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: npm not found on PATH. Install Node.js first." >&2
  exit 1
fi

cd "$FRONTEND_DIR"

echo "==> Node $(node --version) / npm $(npm --version)"

# --- Dependencies -------------------------------------------------------------
if [[ ! -d node_modules ]]; then
  echo "==> Installing dependencies (node_modules missing)..."
  npm install
else
  echo "==> Dependencies already installed."
fi

# --- Launch -------------------------------------------------------------------
if [[ "$MODE" == "preview" ]]; then
  echo "==> Building production bundle..."
  npm run build
  echo "==> Serving production preview on http://$HOST:$PORT ..."
  exec npm run preview -- --host "$HOST" --port "$PORT"
else
  echo "==> Starting Vite dev server on http://$HOST:$PORT ..."
  echo "    (Backend expected at http://localhost:8000 — run ./backend_start.sh)"
  exec npm run dev -- --host "$HOST" --port "$PORT"
fi
