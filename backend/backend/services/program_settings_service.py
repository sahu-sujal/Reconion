from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.exceptions import EntityNotFoundError
from database.models.program import Program
from database.models.program_settings import ProgramSettings

logger = logging.getLogger(__name__)


class ProgramSettingsService:
    """Service layer for program settings CRUD operations."""

    def create_settings(
        self,
        db: Session,
        program_id: uuid.UUID,
        subdomain_scan_enabled: bool = False,
        url_scan_enabled: bool = False,
        js_scan_enabled: bool = False,
        technology_scan_enabled: bool = False,
        screenshot_scan_enabled: bool = False,
        notification_enabled: bool = False,
        scan_frequency: str | None = None,
    ) -> ProgramSettings:
        if db.get(Program, program_id) is None:
            raise EntityNotFoundError("Program", str(program_id))

        settings = ProgramSettings(
            program_id=program_id,
            subdomain_scan_enabled=subdomain_scan_enabled,
            url_scan_enabled=url_scan_enabled,
            js_scan_enabled=js_scan_enabled,
            technology_scan_enabled=technology_scan_enabled,
            screenshot_scan_enabled=screenshot_scan_enabled,
            notification_enabled=notification_enabled,
            scan_frequency=scan_frequency,
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
        logger.info("Program settings created for program: %s", program_id)
        return settings

    def get_settings(self, db: Session, settings_id: uuid.UUID) -> ProgramSettings:
        settings = db.get(ProgramSettings, settings_id)
        if settings is None:
            raise EntityNotFoundError("ProgramSettings", str(settings_id))
        return settings

    def list_settings(
        self,
        db: Session,
        offset: int = 0,
        limit: int = 100,
    ) -> list[ProgramSettings]:
        statement = select(ProgramSettings).offset(offset).limit(limit)
        return db.scalars(statement).all()

    def update_settings(
        self,
        db: Session,
        settings_id: uuid.UUID,
        subdomain_scan_enabled: bool | None = None,
        url_scan_enabled: bool | None = None,
        js_scan_enabled: bool | None = None,
        technology_scan_enabled: bool | None = None,
        screenshot_scan_enabled: bool | None = None,
        notification_enabled: bool | None = None,
        scan_frequency: str | None = None,
    ) -> ProgramSettings:
        settings = self.get_settings(db, settings_id)
        if subdomain_scan_enabled is not None:
            settings.subdomain_scan_enabled = subdomain_scan_enabled
        if url_scan_enabled is not None:
            settings.url_scan_enabled = url_scan_enabled
        if js_scan_enabled is not None:
            settings.js_scan_enabled = js_scan_enabled
        if technology_scan_enabled is not None:
            settings.technology_scan_enabled = technology_scan_enabled
        if screenshot_scan_enabled is not None:
            settings.screenshot_scan_enabled = screenshot_scan_enabled
        if notification_enabled is not None:
            settings.notification_enabled = notification_enabled
        if scan_frequency is not None:
            settings.scan_frequency = scan_frequency
        db.commit()
        db.refresh(settings)
        logger.info("Program settings updated: %s", settings.id)
        return settings

    def delete_settings(self, db: Session, settings_id: uuid.UUID) -> None:
        settings = self.get_settings(db, settings_id)
        db.delete(settings)
        db.commit()
        logger.info("Program settings deleted: %s", settings_id)
