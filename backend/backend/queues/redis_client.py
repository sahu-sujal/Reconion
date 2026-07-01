from __future__ import annotations

import os
from uuid import UUID

import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
SCOPE_LOCK_TTL_SECONDS = 1800


def get_redis_client() -> redis.Redis:
    return redis.from_url(REDIS_URL, decode_responses=True)


def acquire_scope_lock(scope_id: UUID, ttl: int = SCOPE_LOCK_TTL_SECONDS) -> bool:
    client = get_redis_client()
    return bool(client.set(f"scan_lock:{scope_id}", "1", nx=True, ex=ttl))


def release_scope_lock(scope_id: UUID) -> None:
    client = get_redis_client()
    client.delete(f"scan_lock:{scope_id}")


def is_scope_locked(scope_id: UUID) -> bool:
    client = get_redis_client()
    return bool(client.exists(f"scan_lock:{scope_id}"))


# ---------------------------------------------------------------------------
# Scan control signals (pause / stop)
# ---------------------------------------------------------------------------
#
# A running worker polls its control key at safe boundaries (between tools /
# phases / batches). The API writes PAUSE or STOP there; the worker reacts and
# clears the signal. Keys expire so a crashed worker never leaves a stale signal.

CONTROL_PAUSE = "PAUSE"
CONTROL_STOP = "STOP"
_CONTROL_TTL_SECONDS = 6 * 3600  # generous — cleared explicitly by the worker


def _control_key(scan_run_id: UUID | str) -> str:
    return f"scan_control:{scan_run_id}"


def set_scan_control(scan_run_id: UUID | str, signal: str) -> None:
    """Write a control signal (``PAUSE`` or ``STOP``) for a running scan."""
    client = get_redis_client()
    client.set(_control_key(scan_run_id), signal, ex=_CONTROL_TTL_SECONDS)


def get_scan_control(scan_run_id: UUID | str) -> str | None:
    """Return the pending control signal for a scan, or ``None``."""
    client = get_redis_client()
    return client.get(_control_key(scan_run_id))


def clear_scan_control(scan_run_id: UUID | str) -> None:
    """Remove any pending control signal (called by the worker once it reacts)."""
    client = get_redis_client()
    client.delete(_control_key(scan_run_id))
