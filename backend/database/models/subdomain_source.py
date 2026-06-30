from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.models.mixins import UUIDMixin

if TYPE_CHECKING:
    from database.models.subdomain import Subdomain
    from database.models.scan_run import ScanRun


class SubdomainSource(Base, UUIDMixin):
    """Per-scan, per-tool source record for a discovered subdomain.

    Replaces the comma-separated ``source`` string with proper relational rows.
    One row per (subdomain, tool, scan_run) triple.
    """

    __tablename__ = "subdomain_sources"
    __table_args__ = (
        UniqueConstraint(
            "subdomain_id",
            "tool_name",
            "scan_run_id",
            name="uq_subdomain_sources_subdomain_tool_scan",
        ),
    )

    subdomain_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subdomains.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scan_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scan_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    subdomain: Mapped["Subdomain"] = relationship("Subdomain", back_populates="sources")
    scan_run: Mapped["ScanRun"] = relationship("ScanRun", back_populates="subdomain_sources")
