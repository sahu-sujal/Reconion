from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.models.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from database.models.host import Host
    from database.models.program import Program
    from database.models.scope import Scope


class HttpResponse(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "http_responses"
    __table_args__ = (
        UniqueConstraint("host_id", "url", name="uq_http_responses_host_url"),
        Index("ix_http_responses_program_id", "program_id"),
        Index("ix_http_responses_scope_id", "scope_id"),
        Index("ix_http_responses_status_code", "status_code"),
    )

    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scopes.id", ondelete="CASCADE"),
        nullable=False,
    )
    host_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hosts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    server: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # JSON array of technology strings detected by httpx
    technologies: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    response_time: Mapped[float | None] = mapped_column(Float, nullable=True)

    host: Mapped["Host"] = relationship("Host", back_populates="http_responses")
    program: Mapped["Program"] = relationship("Program")
    scope: Mapped["Scope"] = relationship("Scope")
