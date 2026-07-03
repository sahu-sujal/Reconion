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
    from database.models.parameter import Parameter


class ParameterSource(Base, UUIDMixin):
    """Per-tool source attribution for a discovered parameter (Phase 6.4).

    One row per ``(parameter, tool_name)``. Mirrors ``endpoint_sources`` /
    ``js_secret_sources`` so a single parameter can be attributed to Arjun,
    ParamSpider and any future tool independently.
    """

    __tablename__ = "parameter_sources"
    __table_args__ = (
        UniqueConstraint("parameter_id", "tool_name", name="uq_parameter_sources_param_tool"),
    )

    parameter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parameters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    parameter: Mapped["Parameter"] = relationship("Parameter", back_populates="sources")
