from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
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
    from database.models.js_file_source import JsFileSource
    from database.models.program import Program
    from database.models.scope import Scope


class JsFile(Base, UUIDMixin, TimestampMixin):
    """A discovered JavaScript asset (Phase 5 — Content Discovery).

    Deduplicated on ``(scope_id, url)``; per-tool attribution lives in
    :class:`JsFileSource`.
    """

    __tablename__ = "js_files"
    __table_args__ = (
        UniqueConstraint("scope_id", "url", name="uq_js_files_scope_url"),
        Index("ix_js_files_program_id_url", "program_id", "url"),
        Index("ix_js_files_host_id_url", "host_id", "url"),
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
    host_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hosts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    url: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    directory: Mapped[str | None] = mapped_column(Text, nullable=True)
    extension: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    program: Mapped["Program"] = relationship("Program")
    scope: Mapped["Scope"] = relationship("Scope")
    host_ref: Mapped["Host | None"] = relationship("Host")
    sources: Mapped[list["JsFileSource"]] = relationship(
        "JsFileSource",
        back_populates="js_file",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
