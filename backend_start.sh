#!/usr/bin/env bash
#
# backend_start.sh — start the Recon Platform backend stack.
#
# Brings up (in order):
#   1. Redis server         (started if not already running)
#   2. Celery worker        (workers.* tasks)
#   3. Celery beat          (periodic scheduler, e.g. enqueue_pending_scans every 5m)
#   4. Uvicorn / FastAPI    (backend.main:app)
#
# The backend virtualenv (backend/.venv) is activated automatically. Note: the
# venv's `activate` script has a stale hardcoded path (it was created by uv at an
# old location and moved), so we invoke the venv interpreter directly via
# `$VENV_PY -m <module>`, which uses the working `python` symlink in .venv/bin.
#
# Usage:
#   ./backend_start.sh
# Press Ctrl-C to stop the worker, beat, and API (Redis is left running if it
# was already up before this script started).

set -euo pipefail

# --- Paths --------------------------------------------------------------------
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
VENV_PY="$BACKEND_DIR/.venv/bin/python"
LOG_DIR="$ROOT_DIR/logs"

API_HOST="${API_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8000}"

mkdir -p "$LOG_DIR"

# --- Sanity checks ------------------------------------------------------------
if [[ ! -x "$VENV_PY" ]]; then
  echo "ERROR: backend virtualenv interpreter not found at $VENV_PY" >&2
  echo "       Create it first (e.g. 'uv venv' or 'python -m venv .venv' in backend/)." >&2
  exit 1
fi

# Run everything from the backend dir so module imports (backend.*, workers.*,
# database.*) resolve correctly.
cd "$BACKEND_DIR"

echo "==> Using interpreter: $("$VENV_PY" -c 'import sys; print(sys.executable)')"

# --- Redis --------------------------------------------------------------------
# Derive host/port from REDIS_URL in .env if present, else default to localhost:6379.
REDIS_HOST="127.0.0.1"
REDIS_PORT="6379"

REDIS_STARTED_BY_US=0
ensure_redis() {
  if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping >/dev/null 2>&1; then
    echo "==> Redis already running on $REDIS_HOST:$REDIS_PORT"
    return
  fi

  echo "==> Redis not responding — starting redis-server..."
  if ! command -v redis-server >/dev/null 2>&1; then
    echo "ERROR: redis-server not installed and Redis is not running." >&2
    exit 1
  fi

  redis-server --daemonize yes --port "$REDIS_PORT" \
    --logfile "$LOG_DIR/redis.log"
  REDIS_STARTED_BY_US=1

  # Wait for it to accept connections.
  for _ in $(seq 1 20); do
    if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping >/dev/null 2>&1; then
      echo "==> Redis is up."
      return
    fi
    sleep 0.25
  done

  echo "ERROR: Redis did not become ready in time." >&2
  exit 1
}

ensure_redis

# --- Process management / cleanup --------------------------------------------
PIDS=()
CLEANED_UP=0

cleanup() {
  # Guard against the trap firing more than once (INT/TERM then EXIT).
  if [[ "$CLEANED_UP" -eq 1 ]]; then
    return
  fi
  CLEANED_UP=1
  echo
  echo "==> Shutting down backend stack..."
  for pid in "${PIDS[@]:-}"; do
    if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  # Give children a moment to exit cleanly.
  wait 2>/dev/null || true
  if [[ "$REDIS_STARTED_BY_US" -eq 1 ]]; then
    echo "==> Stopping Redis (started by this script)..."
    redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" shutdown nosave >/dev/null 2>&1 || true
  fi
  echo "==> Done."
}
trap cleanup EXIT INT TERM

# --- Celery worker ------------------------------------------------------------
echo "==> Starting Celery worker..."
"$VENV_PY" -m celery -A backend.celery_app:celery_app worker \
  --loglevel=info \
  --logfile="$LOG_DIR/celery_worker.log" &
PIDS+=($!)

# --- Celery beat (periodic scheduler) ----------------------------------------
echo "==> Starting Celery beat..."
"$VENV_PY" -m celery -A backend.celery_app:celery_app beat \
  --loglevel=info \
  --schedule="$BACKEND_DIR/celerybeat-schedule" \
  --logfile="$LOG_DIR/celery_beat.log" &
PIDS+=($!)

# --- FastAPI (uvicorn) --------------------------------------------------------
echo "==> Starting FastAPI on http://$API_HOST:$API_PORT ..."
"$VENV_PY" -m uvicorn backend.main:app \
  --host "$API_HOST" \
  --port "$API_PORT" &
PIDS+=($!)

echo
echo "==> Backend stack is up:"
echo "      API     : http://$API_HOST:$API_PORT  (docs at /docs)"
echo "      Worker  : $LOG_DIR/celery_worker.log"
echo "      Beat    : $LOG_DIR/celery_beat.log"
echo "      Redis   : $REDIS_HOST:$REDIS_PORT"
echo "    Press Ctrl-C to stop."

# Wait on all background jobs; if any exits, trap cleanup tears the rest down.
wait -n
