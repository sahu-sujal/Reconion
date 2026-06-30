from __future__ import annotations

from celery import Celery

from backend.queues.redis_client import REDIS_URL

celery_app = Celery(
    "recon_platform",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "workers.subdomain.subdomain_worker",
        "workers.dns.dns_worker",
        "workers.http.http_worker",
        "workers.url.url_worker",
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
