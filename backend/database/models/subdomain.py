from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.models.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from database.models.asset import Asset
    from database.models.dns_record import DnsRecord
    from database.models.program import Program
    from database.models.scope import Scope
    from database.models.subdomain_source import SubdomainSource


class Subdomain(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "subdomains"
    __table_args__ = (
        UniqueConstraint("scope_id", "subdomain", name="uq_subdomains_scope_subdomain"),
        Index("ix_subdomains_program_id_subdomain", "program_id", "subdomain"),
        Index(
            "ix_subdomains_asset_id_not_null",
            "asset_id",
            postgresql_where=text("asset_id IS NOT NULL"),
        ),
    )

    # asset_id is nullable — bulk upserts no longer require a pre-existing Asset row
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="SET NULL"),
        nullable=True,
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
    subdomain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # source kept for backward-compat display; subdomain_sources is the authoritative table
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Phase 6.1 — maintained endpoint counter (never COUNT()-ed per request)
    endpoint_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    asset: Mapped["Asset | None"] = relationship("Asset", back_populates="subdomains")
    program: Mapped["Program"] = relationship("Program")
    scope: Mapped["Scope"] = relationship("Scope")
    dns_records: Mapped[list["DnsRecord"]] = relationship(
        "DnsRecord", back_populates="subdomain", passive_deletes=True,
    )
    sources: Mapped[list["SubdomainSource"]] = relationship(
        "SubdomainSource",
        back_populates="subdomain",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
