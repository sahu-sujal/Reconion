from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.models.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from database.models.host import Host
    from database.models.program import Program
    from database.models.scope import Scope


class Screenshot(Base, UUIDMixin, TimestampMixin):
    """A page screenshot captured by gowitness for a live host URL.

    One row per (host, url). ``file_path`` is stored relative to the storage
    root so it can be served regardless of where the tree is mounted, and the
    frontend builds ``<STORAGE_BASE>/<file_path>`` to render the image.
    """

    __tablename__ = "screenshots"
    __table_args__ = (
        UniqueConstraint("host_id", "url", name="uq_screenshots_host_url"),
        Index("ix_screenshots_program_id", "program_id"),
        Index("ix_screenshots_scope_id", "scope_id"),
    )

    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scopes.id", ondelete="CASCADE"),
        nullable=False,
    )
    host_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hosts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # gowitness screenshot filename, e.g. "https---example.com-443.jpeg"
    file_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Path relative to the storage root, e.g.
    # "programs/<pid>/scopes/<sid>/screenshots/https---example.com-443.jpeg"
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    failed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    host: Mapped["Host"] = relationship("Host", back_populates="screenshots")
    program: Mapped["Program"] = relationship("Program")
    scope: Mapped["Scope"] = relationship("Scope")
