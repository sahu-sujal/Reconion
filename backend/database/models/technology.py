from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.models.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from database.models.host import Host
    from database.models.program import Program
    from database.models.scope import Scope


class Technology(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "technologies"
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
    host_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hosts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    technology: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    host: Mapped["Host"] = relationship("Host", back_populates="technologies")
    program: Mapped["Program"] = relationship("Program")
    scope: Mapped["Scope"] = relationship("Scope")
