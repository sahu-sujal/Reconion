from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from repositories.base_repository import BaseRepository
from database.models.tool_execution import ToolExecution


class ToolExecutionRepository(BaseRepository[ToolExecution]):
    def __init__(self) -> None:
        super().__init__(ToolExecution)

    def list_by_scan_run(self, db: Session, scan_run_id: uuid.UUID) -> list[ToolExecution]:
        stmt = (
            select(ToolExecution)
            .where(ToolExecution.scan_run_id == scan_run_id)
            .order_by(ToolExecution.started_at)
        )
        return list(db.scalars(stmt).all())
