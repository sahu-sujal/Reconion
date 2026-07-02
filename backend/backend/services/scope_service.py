from __future__ import annotations

import logging
import uuid

from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.exceptions import EntityNotFoundError
from database.models.enums import ScanType, ScopeType
from database.models.program import Program
from database.models.scope import Scope
from database.models.asset import Asset
from database.models.finding import Finding
from database.models.endpoint import Endpoint
from database.models.js_file import JsFile
from database.models.notification import Notification
from database.models.scan_run import ScanRun
from database.models.url import URL

logger = logging.getLogger(__name__)


class ScopeService:
    """Service layer for scope CRUD operations."""

    def create_scope(
        self,
        db: Session,
        program_id: uuid.UUID,
        target: str,
        scope_type: str = ScopeType.ROOT_DOMAIN.value,
        priority: int = 50,
        is_active: bool = True,
        notes: str | None = None,
    ) -> Scope:
        program = db.get(Program, program_id)
        if program is None:
            raise EntityNotFoundError("Program", str(program_id))

        allowed_scope_types = {stype.value for stype in ScopeType}
        if scope_type not in allowed_scope_types:
            raise ValueError(f"Invalid scope type: {scope_type}")

        scope = Scope(
            program_id=program_id,
            target=target,
            scope_type=scope_type,
            priority=priority,
            is_active=is_active,
            notes=notes,
        )
        db.add(scope)
        db.commit()
        db.refresh(scope)
        logger.info("Scope created: %s", scope.id)
        return scope

    def get_scope(self, db: Session, scope_id: uuid.UUID) -> Scope:
        scope = db.get(Scope, scope_id)
        if scope is None:
            raise EntityNotFoundError("Scope", str(scope_id))
        return scope

    def list_scopes(
        self,
        db: Session,
        program_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Scope]:
        statement = select(Scope)
        if program_id is not None:
            statement = statement.filter(Scope.program_id == program_id)
        statement = statement.offset(offset).limit(limit)
        return db.scalars(statement).all()

    def list_scopes_for_program(
        self,
        db: Session,
        program_id: uuid.UUID,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Scope]:
        if db.get(Program, program_id) is None:
            raise EntityNotFoundError("Program", str(program_id))

        statement = select(Scope).filter(Scope.program_id == program_id)
        statement = statement.offset(offset).limit(limit)
        return db.scalars(statement).all()

    def update_scope(
        self,
        db: Session,
        scope_id: uuid.UUID,
        scope_type: str | None = None,
        priority: int | None = None,
        is_active: bool | None = None,
        notes: str | None = None,
    ) -> Scope:
        scope = self.get_scope(db, scope_id)
        if scope_type is not None:
            allowed_scope_types = {stype.value for stype in ScopeType}
            if scope_type not in allowed_scope_types:
                raise ValueError(f"Invalid scope type: {scope_type}")
            scope.scope_type = scope_type
        if priority is not None:
            scope.priority = priority
        if is_active is not None:
            scope.is_active = is_active
        if notes is not None:
            scope.notes = notes
        db.commit()
        db.refresh(scope)
        logger.info("Scope updated: %s", scope.id)
        return scope

    def get_scope_stats(self, db: Session, scope_id: uuid.UUID) -> dict[str, object]:
        scope = self.get_scope(db, scope_id)

        assets_count = db.scalar(
            select(func.count()).select_from(Asset).where(Asset.scope_id == scope_id)
        )
        findings_count = db.scalar(
            select(func.count()).select_from(Finding).where(Finding.scope_id == scope_id)
        )
        notifications_sent = db.scalar(
            select(func.count()).select_from(Notification).where(
                Notification.scope_id == scope_id,
                Notification.sent == True,
            )
        )
        last_notification_at = db.scalar(
            select(func.max(Notification.sent_at)).where(Notification.scope_id == scope_id)
        )

        # Content discovery (Phase 5) totals are true row counts — URLs for
        # out-of-scope hosts have host_id=NULL and would be missed by
        # SUM(hosts.url_count).
        urls_count = db.scalar(
            select(func.count()).select_from(URL).where(URL.scope_id == scope_id)
        )
        js_count = db.scalar(
            select(func.count()).select_from(JsFile).where(JsFile.scope_id == scope_id)
        )
        latest_cd = db.scalar(
            select(ScanRun)
            .where(
                ScanRun.scope_id == scope_id,
                ScanRun.scan_type == ScanType.CONTENT_DISCOVERY.value,
            )
            .order_by(ScanRun.started_at.desc())
            .limit(1)
        )
        new_urls = int(getattr(latest_cd, "new_urls_count", 0) or 0) if latest_cd else 0
        new_js = int(getattr(latest_cd, "new_js_count", 0) or 0) if latest_cd else 0

        # JS endpoint discovery (Phase 6.1) — true row count; new count from the
        # latest JS_ENDPOINT scan run.
        endpoints_count = db.scalar(
            select(func.count()).select_from(Endpoint).where(Endpoint.scope_id == scope_id)
        )
        latest_ep = db.scalar(
            select(ScanRun)
            .where(
                ScanRun.scope_id == scope_id,
                ScanRun.scan_type == ScanType.JS_ENDPOINT.value,
            )
            .order_by(ScanRun.started_at.desc())
            .limit(1)
        )
        new_endpoints = int(getattr(latest_ep, "new_endpoints_count", 0) or 0) if latest_ep else 0

        # JS secret discovery (Phase 6.2).
        from database.models.js_secret import JsSecret
        secrets_count = db.scalar(
            select(func.count()).select_from(JsSecret).where(JsSecret.scope_id == scope_id)
        )
        latest_sec = db.scalar(
            select(ScanRun)
            .where(ScanRun.scope_id == scope_id, ScanRun.scan_type == ScanType.JS_SECRET.value)
            .order_by(ScanRun.started_at.desc())
            .limit(1)
        )
        new_secrets = int(getattr(latest_sec, "new_secrets_count", 0) or 0) if latest_sec else 0

        return {
            "scope_id": scope.id,
            "assets_count": int(assets_count or 0),
            "findings_count": int(findings_count or 0),
            "notifications_sent": int(notifications_sent or 0),
            "urls_count": int(urls_count or 0),
            "new_urls": new_urls,
            "js_count": int(js_count or 0),
            "new_js": new_js,
            "endpoints_count": int(endpoints_count or 0),
            "new_endpoints": new_endpoints,
            "secrets_count": int(secrets_count or 0),
            "new_secrets": new_secrets,
            "last_scan_at": scope.last_scan_at,
            "last_notification_at": last_notification_at,
        }

    def delete_scope(self, db: Session, scope_id: uuid.UUID) -> None:
        scope = self.get_scope(db, scope_id)

        # Resolve storage identifiers before the row is gone
        program = db.get(Program, scope.program_id)
        program_id = scope.program_id
        program_name = program.name if program else None
        scope_target = scope.target

        db.delete(scope)
        db.commit()
        logger.info("Scope deleted: %s", scope_id)

        # Remove the scope's filesystem directories after the DB commit succeeds.
        # Workers write artifacts to the UUID-keyed tree
        # (storage/programs/{program_id}/scopes/{scope_id}/...); the legacy
        # name-based tree is also removed for backward compatibility.
        try:
            import shutil

            from backend.services.storage_service import StorageService

            storage = StorageService()
            paths_to_remove = [storage.get_scope_path_by_id(program_id, scope_id)]
            if program_name:
                paths_to_remove.append(storage.get_scope_path(program_name, scope_target))

            for scope_path in paths_to_remove:
                if scope_path.exists():
                    shutil.rmtree(scope_path)
                    logger.info("Removed scope storage directory: %s", scope_path)
        except Exception as exc:
            logger.warning("Failed to remove scope storage directory: %s", exc)
