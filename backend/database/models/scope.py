from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.models.enums import ScopeType
from database.models.mixins import SoftDeleteMixin, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from database.models.asset import Asset
    from database.models.finding import Finding
    from database.models.notification import Notification
    from database.models.program import Program
    from database.models.scan_run import ScanRun


class Scope(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "scopes"
    __table_args__ = (
        UniqueConstraint("program_id", "target", name="uq_scopes_program_target"),
        CheckConstraint(
            "scope_type IN ('ROOT_DOMAIN', 'WILDCARD_DOMAIN', 'SUBDOMAIN', 'URL', 'CIDR', 'IP_RANGE')",
            name="ck_scopes_scope_type",
        ),
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ScopeType.ROOT_DOMAIN.value,
        server_default="ROOT_DOMAIN",
        index=True,
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=50,
        server_default="50",
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        index=True,
    )
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    program: Mapped["Program"] = relationship("Program", back_populates="scopes")
    assets: Mapped[list["Asset"]] = relationship(
        "Asset",
        back_populates="scope",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    scan_runs: Mapped[list["ScanRun"]] = relationship(
        "ScanRun",
        back_populates="scope",
        cascade="all, delete-orphan",
    )
    findings: Mapped[list["Finding"]] = relationship(
        "Finding",
        back_populates="scope",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    notifications: Mapped[list["Notification"]] = relationship(
        "Notification",
        back_populates="scope",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
