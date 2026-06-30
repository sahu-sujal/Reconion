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
    from database.models.js_file import JsFile


class JsFileSource(Base, UUIDMixin):
    """Per-tool source attribution for a discovered JS file.

    One row per (js_file, tool_name).
    """

    __tablename__ = "js_file_sources"
    __table_args__ = (
        UniqueConstraint("js_file_id", "tool_name", name="uq_js_file_sources_js_tool"),
    )

    js_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("js_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    js_file: Mapped["JsFile"] = relationship("JsFile", back_populates="sources")
