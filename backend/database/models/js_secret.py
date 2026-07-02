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
    from database.models.js_file import JsFile
    from database.models.js_secret_source import JsSecretSource
    from database.models.program import Program
    from database.models.scope import Scope


class JsSecret(Base, UUIDMixin, TimestampMixin):
    """A secret discovered inside a JavaScript file (Phase 6.2).

    The **complete, unmasked** secret value is stored so analysts can verify and
    report it. Deduplication is keyed on ``(scope_id, fingerprint)`` where the
    fingerprint is a stable hash of ``(secret_type, normalized_secret)`` — so the
    same key found in multiple JS files/tools collapses to one record.
    ``discovery_tools`` is a JSON array of every scanner that flagged it; per-tool
    provenance lives in :class:`JsSecretSource`.

    The schema is scanner- and type-agnostic: adding a new scanner only appends a
    label to ``discovery_tools``; adding a new secret_type needs no migration
    (it is a plain string).
    """

    __tablename__ = "js_secrets"
    __table_args__ = (
        UniqueConstraint("scope_id", "fingerprint", name="uq_js_secrets_scope_fingerprint"),
        Index("ix_js_secrets_program_id_severity", "program_id", "severity"),
        Index("ix_js_secrets_scope_id_type", "scope_id", "secret_type"),
        Index("ix_js_secrets_host_id_type", "host_id", "secret_type"),
        Index("ix_js_secrets_normalized_secret", "normalized_secret"),
        Index("ix_js_secrets_js_file_url", "js_file_url"),
        # GIN index for discovery_tools JSONB membership queries.
        Index("ix_js_secrets_discovery_tools_gin", "discovery_tools", postgresql_using="gin"),
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

    # Denormalized so an analyst can reproduce the finding without extra lookups.
    js_file_url: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    host: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    secret_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # The raw secret exactly as discovered — NEVER masked (see Phase 6.2 policy).
    secret_value: Mapped[str] = mapped_column(Text, nullable=False)
    # Canonicalised value used for dedup/fingerprint (e.g. trimmed).
    normalized_secret: Mapped[str] = mapped_column(Text, nullable=False)
    # sha256(secret_type + '|' + normalized_secret) — the stable dedup key.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=50, server_default="50")
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, default="INFO", server_default="INFO", index=True,
    )

    discovery_tools: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]",
    )

    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    program: Mapped["Program"] = relationship("Program")
    scope: Mapped["Scope"] = relationship("Scope")
    host_ref: Mapped["Host | None"] = relationship("Host")
    js_file: Mapped["JsFile | None"] = relationship("JsFile")
    sources: Mapped[list["JsSecretSource"]] = relationship(
        "JsSecretSource",
        back_populates="secret",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
