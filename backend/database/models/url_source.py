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
    from database.models.url import URL


class UrlSource(Base, UUIDMixin):
    """Per-tool source attribution for a discovered URL.

    One row per (url, tool_name). Records which crawler/historical tool
    found a given URL so the UI can show e.g. ``GAU, WAYBACKURLS, KATANA``.
    """

    __tablename__ = "url_sources"
    __table_args__ = (
        UniqueConstraint("url_id", "tool_name", name="uq_url_sources_url_tool"),
    )

    url_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("urls.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    url: Mapped["URL"] = relationship("URL", back_populates="sources")
