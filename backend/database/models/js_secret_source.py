from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.models.mixins import UUIDMixin

if TYPE_CHECKING:
    from database.models.js_secret import JsSecret


class JsSecretSource(Base, UUIDMixin):
    """Per-scanner attribution for a discovered secret (Phase 6.2).

    One row per ``(secret, tool_name)`` — so a single secret can be attributed to
    SecretFinder, Mantra and Nuclei Exposures independently.
    """

    __tablename__ = "js_secret_sources"
    __table_args__ = (
        UniqueConstraint("secret_id", "tool_name", name="uq_js_secret_sources_secret_tool"),
    )

    secret_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("js_secrets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    secret: Mapped["JsSecret"] = relationship("JsSecret", back_populates="sources")
