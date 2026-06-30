from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.models.enums import ProgramStatus
from database.models.mixins import SoftDeleteMixin, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from database.models.asset import Asset
    from database.models.finding import Finding
    from database.models.program_settings import ProgramSettings
    from database.models.scan_run import ScanRun
    from database.models.scope import Scope
    from database.models.notification import Notification


class Program(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "programs"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    platform: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=ProgramStatus.ACTIVE.value,
        server_default=ProgramStatus.ACTIVE.value,
        index=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    scopes: Mapped[list["Scope"]] = relationship(
        "Scope",
        back_populates="program",
        cascade="all, delete-orphan",
    )
    settings: Mapped["ProgramSettings"] = relationship(
        "ProgramSettings",
        back_populates="program",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    assets: Mapped[list["Asset"]] = relationship(
        "Asset",
        back_populates="program",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    scan_runs: Mapped[list["ScanRun"]] = relationship(
        "ScanRun",
        back_populates="program",
        cascade="all, delete-orphan",
    )
    findings: Mapped[list["Finding"]] = relationship(
        "Finding",
        back_populates="program",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    notifications: Mapped[list["Notification"]] = relationship(
        "Notification",
        back_populates="program",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
