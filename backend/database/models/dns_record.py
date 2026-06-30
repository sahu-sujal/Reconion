from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.models.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from database.models.host import Host
    from database.models.program import Program
    from database.models.scope import Scope
    from database.models.subdomain import Subdomain

# Supported DNS record types
DNS_RECORD_TYPES = ("A", "AAAA", "CNAME", "MX", "TXT", "NS")


class DnsRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "dns_records"
    __table_args__ = (
        UniqueConstraint(
            "host_id", "record_type", "record_value",
            name="uq_dns_records_host_type_value",
        ),
        Index("ix_dns_records_program_id", "program_id"),
        Index("ix_dns_records_scope_id", "scope_id"),
        Index("ix_dns_records_record_type", "record_type"),
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
    subdomain_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subdomains.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    record_type: Mapped[str] = mapped_column(String(16), nullable=False)
    record_value: Mapped[str] = mapped_column(Text, nullable=False)
    ttl: Mapped[int | None] = mapped_column(Integer, nullable=True)

    host: Mapped["Host"] = relationship("Host", back_populates="dns_records")
    subdomain: Mapped["Subdomain | None"] = relationship("Subdomain", back_populates="dns_records")
    program: Mapped["Program"] = relationship("Program")
    scope: Mapped["Scope"] = relationship("Scope")
