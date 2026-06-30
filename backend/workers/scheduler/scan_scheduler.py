from __future__ import annotations

from celery.schedules import crontab
from backend.celery_app import celery_app


@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs) -> None:
    sender.add_periodic_task(
        crontab(minute="*/5"),
        enqueue_pending_scans.s(),
        name="enqueue_pending_scans_every_5_minutes",
    )


@celery_app.task(name="workers.scheduler.scan_scheduler.enqueue_pending_scans")
def enqueue_pending_scans() -> None:
    # This scheduler task is a heartbeat for pending scans.
    # The scan orchestrator queues work when an API request arrives.
    return None
