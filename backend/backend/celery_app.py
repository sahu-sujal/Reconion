from __future__ import annotations

import logging

from celery import Celery
from celery.signals import worker_ready

from backend.queues.redis_client import REDIS_URL

logger = logging.getLogger(__name__)

celery_app = Celery(
    "recon_platform",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "workers.subdomain.subdomain_worker",
        "workers.dns.dns_worker",
        "workers.http.http_worker",
        "workers.url.url_worker",
        "workers.js_endpoint_worker",
        "workers.notification.discord_worker",
        "workers.scheduler.scan_scheduler",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_send_task_events=True,
    task_track_started=True,
)


@worker_ready.connect
def _log_tool_availability(**_kwargs) -> None:
    """On worker boot, log which recon tools resolved (bundled vs. missing).

    A missing tool doesn't stop the worker — that tool's step is recorded as
    failed and skipped — but surfacing it once at startup makes a mis-provisioned
    host obvious instead of silently producing empty results.
    """
    try:
        from tools.common.tool_paths import TOOLS_BIN, tool_availability

        avail = tool_availability()
        present = sorted(n for n, p in avail.items() if p)
        missing = sorted(n for n, p in avail.items() if not p)
        logger.info("Recon tools dir: %s", TOOLS_BIN)
        logger.info("Recon tools available (%d): %s", len(present), ", ".join(present))
        if missing:
            logger.warning(
                "Recon tools MISSING (%d) — their steps will be skipped: %s",
                len(missing), ", ".join(missing),
            )
    except Exception as exc:  # diagnostics must never break worker startup
        logger.warning("Tool availability check failed: %s", exc)
