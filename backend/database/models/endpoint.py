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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.models.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from database.models.endpoint_source import EndpointSource
    from database.models.host import Host
    from database.models.js_file import JsFile
    from database.models.program import Program
    from database.models.scope import Scope


class Endpoint(Base, UUIDMixin, TimestampMixin):
    """A fully-qualified endpoint extracted from a JavaScript file (Phase 6.1).

    Every endpoint is stored as an **absolute** URL resolved against the JS file
    it originated from. Deduplication is keyed on ``(scope_id, normalized_url)``;
    ``discovery_tools`` is a JSON array tracking every extractor that found the
    endpoint, and per-tool provenance rows live in :class:`EndpointSource`.

    The schema is extractor-agnostic: adding JSluice / Mantra / a custom AST
    parser later only appends new labels to ``discovery_tools`` — no migration.
    """

    __tablename__ = "endpoints"
    __table_args__ = (
        UniqueConstraint("scope_id", "normalized_url", name="uq_endpoints_scope_normalized"),
        Index("ix_endpoints_normalized_url", "normalized_url"),
        Index("ix_endpoints_program_id_normalized", "program_id", "normalized_url"),
        Index("ix_endpoints_scope_id_normalized", "scope_id", "normalized_url"),
        Index("ix_endpoints_host_id_normalized", "host_id", "normalized_url"),
        Index("ix_endpoints_js_file_id_created", "js_file_id", "created_at"),
        # GIN index for discovery_tools JSONB membership queries (?, @>).
        Index(
            "ix_endpoints_discovery_tools_gin",
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
    js_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("js_files.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    absolute_url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    scheme: Mapped[str | None] = mapped_column(String(16), nullable=True)
    host: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    fragment: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Free-form JSON array of EndpointTool labels — extractor-agnostic.
    discovery_tools: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]",
    )
    discovery_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="JS_DISCOVERY",
        server_default="JS_DISCOVERY", index=True,
    )
    # The originating JS file URL (kept denormalized for search even if the JS
    # row is later pruned and js_file_id goes NULL).
    source_js_file: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)

    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    program: Mapped["Program"] = relationship("Program")
    scope: Mapped["Scope"] = relationship("Scope")
    host_ref: Mapped["Host | None"] = relationship("Host")
    js_file: Mapped["JsFile | None"] = relationship("JsFile")
    sources: Mapped[list["EndpointSource"]] = relationship(
        "EndpointSource",
        back_populates="endpoint",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
