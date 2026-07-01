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
    from database.models.endpoint import Endpoint


class EndpointSource(Base, UUIDMixin):
    """Per-tool source attribution for a discovered endpoint (Phase 6.1).

    One row per ``(endpoint, tool_name)``. Mirrors ``url_sources`` /
    ``js_file_sources`` so a single endpoint can be attributed to LinkFinder,
    XNLinkFinder and any future extractor independently.
    """

    __tablename__ = "endpoint_sources"
    __table_args__ = (
        UniqueConstraint("endpoint_id", "tool_name", name="uq_endpoint_sources_endpoint_tool"),
    )

    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("endpoints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    endpoint: Mapped["Endpoint"] = relationship("Endpoint", back_populates="sources")
