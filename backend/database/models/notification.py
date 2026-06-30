from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.models.enums import NotificationChannel
from database.models.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from database.models.finding import Finding
    from database.models.program import Program
    from database.models.scope import Scope


class Notification(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "notifications"
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
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("findings.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notification_channel", native_enum=False),
        nullable=False,
        index=True,
    )
    sent: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        index=True,
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    program: Mapped["Program"] = relationship("Program", back_populates="notifications")
    scope: Mapped["Scope"] = relationship("Scope", back_populates="notifications")
    finding: Mapped["Finding"] = relationship(
        "Finding",
        foreign_keys=[finding_id],
        uselist=False,
    )
