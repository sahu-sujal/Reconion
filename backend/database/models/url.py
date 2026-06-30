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
    from database.models.url_source import UrlSource


class URL(Base, UUIDMixin, TimestampMixin):
    """A single discovered URL (Phase 5 — Content Discovery).

    Deduplication key is ``(scope_id, normalized_url)`` — every tool that
    rediscovers the same normalized URL upserts onto the same row, and the
    per-tool attribution lives in :class:`UrlSource`.
    """

    __tablename__ = "urls"
    __table_args__ = (
        UniqueConstraint("scope_id", "normalized_url", name="uq_urls_scope_normalized"),
        Index("ix_urls_program_id_normalized", "program_id", "normalized_url"),
        Index("ix_urls_host_id_normalized", "host_id", "normalized_url"),
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
    # host_id is nullable — historical URLs may reference a host that is not
    # (yet) a resolved Host row for this scope.
    host_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hosts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    scheme: Mapped[str | None] = mapped_column(String(16), nullable=True)
    host: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    fragment: Mapped[str | None] = mapped_column(Text, nullable=True)
    extension: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    directory: Mapped[str | None] = mapped_column(Text, nullable=True)
    filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    parameter_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    has_parameters: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )
    status: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Denormalized comma-separated source string for quick display; the
    # authoritative per-tool attribution lives in url_sources.
    source: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    program: Mapped["Program"] = relationship("Program")
    scope: Mapped["Scope"] = relationship("Scope")
    host_ref: Mapped["Host | None"] = relationship("Host")
    sources: Mapped[list["UrlSource"]] = relationship(
        "UrlSource",
        back_populates="url",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
