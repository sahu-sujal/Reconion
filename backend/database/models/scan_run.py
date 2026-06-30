from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.models.enums import ScanStatus, ScanType
from database.models.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from database.models.program import Program
    from database.models.scope import Scope
    from database.models.subdomain_source import SubdomainSource
    from database.models.tool_execution import ToolExecution


class ScanRun(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "scan_runs"
    __table_args__ = (
        CheckConstraint(
            "scan_type IN ('SUBDOMAIN', 'DNS', 'HTTP', 'PORT', 'URL', 'JS', 'TECHNOLOGY', 'SCREENSHOT')",
            name="ck_scan_runs_scan_type",
        ),
    )

    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scopes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scan_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ScanType.SUBDOMAIN.value,
        server_default="SUBDOMAIN",
        index=True,
    )
    worker_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ScanStatus] = mapped_column(
        Enum(ScanStatus, name="scan_status", native_enum=False),
        nullable=False,
        default=ScanStatus.PENDING,
        server_default="PENDING",
        index=True,
    )
    records_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Per-tool and aggregate metrics populated by the worker at scan completion
    subfinder_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    assetfinder_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    knockpy_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    dnsgen_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    chaos_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    crtsh_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    findomain_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    merged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unique_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    new_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    existing_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # DNS scan metrics
    dnsx_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    resolved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    new_hosts_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # HTTP scan metrics
    httpx_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    live_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    new_live_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    program: Mapped["Program"] = relationship("Program", back_populates="scan_runs")
    scope: Mapped["Scope"] = relationship("Scope", back_populates="scan_runs")
    tool_executions: Mapped[list["ToolExecution"]] = relationship(
        "ToolExecution",
        back_populates="scan_run",
        cascade="all, delete-orphan",
    )
    subdomain_sources: Mapped[list["SubdomainSource"]] = relationship(
        "SubdomainSource",
        back_populates="scan_run",
        cascade="all, delete-orphan",
    )
