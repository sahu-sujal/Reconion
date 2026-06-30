from __future__ import annotations

import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from database.session import SessionLocal
from backend.services.scan_run_service import ScanRunService
from sqlalchemy.orm import Session


class BaseWorker:
    def __init__(self, name: str) -> None:
        self.name = name
        self.logger = self._configure_logger(name)
        self.scan_run_service = ScanRunService()

    def _configure_logger(self, worker_name: str) -> logging.Logger:
        log_dir = Path("logs") / "workers"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{worker_name}.log"

        logger = logging.getLogger(worker_name)
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = RotatingFileHandler(
                log_file,
                maxBytes=5_242_880,
                backupCount=5,
                encoding="utf-8",
            )
            formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def get_db(self) -> Session:
        return SessionLocal()

    def mark_running(self, scan_run_id: str) -> None:
        db = self.get_db()
        try:
            self.scan_run_service.update_scan_run(
                db=db,
                scan_run_id=scan_run_id,
                status="RUNNING",
            )
        finally:
            db.close()

    def mark_completed(self, scan_run_id: str, records_found: int) -> None:
        db = self.get_db()
        try:
            self.scan_run_service.update_scan_run(
                db=db,
                scan_run_id=scan_run_id,
                status="COMPLETED",
                records_found=records_found,
                finished_at=datetime.now(timezone.utc),
            )
        finally:
            db.close()

    def mark_failed(self, scan_run_id: str, error_message: str) -> None:
        db = self.get_db()
        try:
            self.scan_run_service.update_scan_run(
                db=db,
                scan_run_id=scan_run_id,
                status="FAILED",
                error_message=error_message,
                finished_at=datetime.now(timezone.utc),
            )
        finally:
            db.close()
