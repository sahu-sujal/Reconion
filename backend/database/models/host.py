from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.models.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from database.models.asset import Asset
    from database.models.dns_record import DnsRecord
    from database.models.http_response import HttpResponse
    from database.models.program import Program
    from database.models.scope import Scope
    from database.models.technology import Technology


class Host(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "hosts"
    __table_args__ = (
        UniqueConstraint("scope_id", "host", name="uq_hosts_scope_host"),
    )

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
    host: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    ip: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    scheme: Mapped[str | None] = mapped_column(String(16), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    cdn: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True,
    )
    waf: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True,
    )
    # Phase 5 — maintained counters (never COUNT()-ed per request)
    url_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    js_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Phase 6.1 — maintained endpoint counter (never COUNT()-ed per request)
    endpoint_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    asset: Mapped["Asset"] = relationship("Asset", back_populates="hosts")
    program: Mapped["Program"] = relationship("Program")
    scope: Mapped["Scope"] = relationship("Scope")
    technologies: Mapped[list["Technology"]] = relationship(
        "Technology", back_populates="host", cascade="all, delete-orphan", passive_deletes=True,
    )
    dns_records: Mapped[list["DnsRecord"]] = relationship(
        "DnsRecord", back_populates="host", cascade="all, delete-orphan", passive_deletes=True,
    )
    http_responses: Mapped[list["HttpResponse"]] = relationship(
        "HttpResponse", back_populates="host", cascade="all, delete-orphan", passive_deletes=True,
    )
