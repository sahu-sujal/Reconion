from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.models.enums import ToolExecutionStatus
from database.models.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from database.models.scan_run import ScanRun


class ToolExecution(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "tool_executions"

    scan_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scan_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ToolExecutionStatus] = mapped_column(
        Enum(ToolExecutionStatus, name="tool_execution_status", native_enum=False),
        nullable=False,
        default=ToolExecutionStatus.PENDING,
        server_default=ToolExecutionStatus.PENDING.value,
        index=True,
    )
    output_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    raw_records_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    records_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    scan_run: Mapped["ScanRun"] = relationship("ScanRun", back_populates="tool_executions")
