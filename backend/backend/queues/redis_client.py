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
