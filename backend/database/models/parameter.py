from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.models.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from database.models.host import Host
    from database.models.parameter_source import ParameterSource
    from database.models.program import Program
    from database.models.scope import Scope


class Parameter(Base, UUIDMixin, TimestampMixin):
    """A hidden/known HTTP parameter discovered by active enumeration (Phase 6.4).

    Every parameter is linked to the originating asset (a URL or an Endpoint) via
    ``asset_id`` + ``asset_type`` and denormalizes the ``asset_url`` and ``host``
    for search. Deduplication is keyed on ``(scope_id, asset_id, parameter_name)``
    so the same parameter found on two different assets is two rows, but the same
    parameter rediscovered on one asset by another tool upserts onto one row and
    *unions* ``discovery_tools`` — ``first_seen`` is never overwritten.

    The schema is tool-agnostic: adding ParamMiner / a custom dictionary / an AI
    module later only appends new labels to ``discovery_tools`` — no migration.
    ``parameter_type`` is a plain string (see :mod:`tools.common.parameter_utils`)
    so new types need no migration either.
    """

    __tablename__ = "parameters"
    __table_args__ = (
        UniqueConstraint(
            "scope_id", "asset_id", "parameter_name",
            name="uq_parameters_scope_asset_name",
        ),
        Index("ix_parameters_program_id_name", "program_id", "parameter_name"),
        Index("ix_parameters_scope_id_name", "scope_id", "parameter_name"),
        Index("ix_parameters_host_id_name", "host_id", "parameter_name"),
        Index("ix_parameters_asset_id", "asset_id"),
        Index("ix_parameters_parameter_type", "parameter_type"),
        # GIN index for discovery_tools JSONB membership queries (?, @>).
        Index(
            "ix_parameters_discovery_tools_gin",
            "discovery_tools",
            postgresql_using="gin",
        ),
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

    # The originating asset. ``asset_id`` references either urls.id or
    # endpoints.id (disambiguated by ``asset_type``); no FK because it is
    # polymorphic across two tables — the (scope_id, asset_id) pair is unique.
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False)  # URL | ENDPOINT
    asset_url: Mapped[str] = mapped_column(Text, nullable=False)
    host: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    parameter_name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    parameter_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="UNKNOWN", server_default="UNKNOWN",
    )
    # How the parameter entered the inventory (reserved: ACTIVE for Arjun/ParamSpider).
    parameter_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ACTIVE", server_default="ACTIVE",
    )

    # Free-form JSON array of ParameterTool labels — tool-agnostic.
    discovery_tools: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]",
    )

    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    program: Mapped["Program"] = relationship("Program")
    scope: Mapped["Scope"] = relationship("Scope")
    host_ref: Mapped["Host | None"] = relationship("Host")
    sources: Mapped[list["ParameterSource"]] = relationship(
        "ParameterSource",
        back_populates="parameter",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
