from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.models.enums import AssetType
from database.models.mixins import SoftDeleteMixin, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from database.models.finding import Finding
    from database.models.program import Program
    from database.models.scope import Scope
    from database.models.subdomain import Subdomain
    from database.models.host import Host


class Asset(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("program_id", "scope_id", "asset_value", name="uq_assets_program_scope_value"),
        CheckConstraint(
            "asset_type IN ('SUBDOMAIN', 'HOST', 'URL', 'JS', 'CLOUD', 'IP', 'PORT')",
            name="ck_assets_asset_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
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
    asset_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AssetType.SUBDOMAIN.value,
        server_default="SUBDOMAIN",
        index=True,
    )
    asset_value: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    program: Mapped["Program"] = relationship("Program", back_populates="assets")
    scope: Mapped["Scope"] = relationship("Scope", back_populates="assets")
    subdomains: Mapped[list["Subdomain"]] = relationship(
        "Subdomain",
        back_populates="asset",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    hosts: Mapped[list["Host"]] = relationship(
        "Host",
        back_populates="asset",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    findings: Mapped[list["Finding"]] = relationship(
        "Finding",
        back_populates="asset",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
