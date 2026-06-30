from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.models.enums import FindingSeverity, FindingStatus
from database.models.mixins import SoftDeleteMixin, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from database.models.asset import Asset
    from database.models.program import Program
    from database.models.scope import Scope


class Finding(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "findings"
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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
    category: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[FindingSeverity] = mapped_column(
        Enum(FindingSeverity, name="finding_severity", native_enum=False),
        nullable=False,
        default=FindingSeverity.MEDIUM,
        server_default="MEDIUM",
        index=True,
    )
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[FindingStatus] = mapped_column(
        Enum(FindingStatus, name="finding_status", native_enum=False),
        nullable=False,
        default=FindingStatus.NEW,
        server_default="NEW",
        index=True,
    )
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    asset: Mapped["Asset"] = relationship("Asset", back_populates="findings")
    program: Mapped["Program"] = relationship("Program", back_populates="findings")
    scope: Mapped["Scope"] = relationship("Scope", back_populates="findings")
