from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, declared_attr


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        server_onupdate=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        index=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )


class AssetClassificationMixin:
    """Asset-classification columns (Phase 6.3) shared by urls/endpoints/js_files.

    Populated by the Asset Classification Engine from stored data only — no
    network. ``asset_category`` is the primary key of the taxonomy; the boolean
    traits are denormalized from the category so the Asset Explorer and later
    phases filter with a plain indexed boolean. ``extension`` / ``has_parameters``
    are intentionally NOT declared here — those pre-exist on some tables with
    table-specific semantics; each model owns them.
    """

    # NULL until the classifier has run; indexed for per-category listing.
    asset_category: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True,
    )
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)

    @declared_attr
    def is_static(cls) -> Mapped[bool]:  # noqa: N805
        return mapped_column(Boolean, nullable=False, default=False, server_default="false")

    @declared_attr
    def is_dynamic(cls) -> Mapped[bool]:  # noqa: N805
        return mapped_column(Boolean, nullable=False, default=False, server_default="false")

    @declared_attr
    def is_api(cls) -> Mapped[bool]:  # noqa: N805
        return mapped_column(Boolean, nullable=False, default=False, server_default="false", index=True)

    @declared_attr
    def is_document(cls) -> Mapped[bool]:  # noqa: N805
        return mapped_column(Boolean, nullable=False, default=False, server_default="false")

    @declared_attr
    def is_script(cls) -> Mapped[bool]:  # noqa: N805
        return mapped_column(Boolean, nullable=False, default=False, server_default="false")

    @declared_attr
    def is_archive(cls) -> Mapped[bool]:  # noqa: N805
        return mapped_column(Boolean, nullable=False, default=False, server_default="false")

    @declared_attr
    def is_configuration(cls) -> Mapped[bool]:  # noqa: N805
        return mapped_column(Boolean, nullable=False, default=False, server_default="false")

    @declared_attr
    def is_backup(cls) -> Mapped[bool]:  # noqa: N805
        return mapped_column(Boolean, nullable=False, default=False, server_default="false", index=True)

    @declared_attr
    def is_credential(cls) -> Mapped[bool]:  # noqa: N805
        return mapped_column(Boolean, nullable=False, default=False, server_default="false", index=True)


class GfClassificationMixin:
    """GF (security-relevance) classification columns, shared by urls/endpoints.

    Populated by the GF scan phase from stored data only — no network. Whereas
    :class:`AssetClassificationMixin` answers "what kind of thing is this?",
    these columns answer "why might this be interesting to an attacker?".

    ``gf_tags`` is a JSONB array of gf category names (e.g. ``["sqli", "xss"]``)
    kept free-form so new patterns can be added by dropping a JSON file into
    ``tools/gf-patterns/`` — no schema change. It is GIN-indexed per table so
    membership queries (``gf_tags ? 'sqli'``) stay fast on large inventories.
    ``gf_tag_count`` is denormalized so "has any match" filtering and sorting
    avoid unnesting the array.
    """

    @declared_attr
    def gf_tags(cls) -> Mapped[list]:  # noqa: N805
        return mapped_column(JSONB, nullable=False, default=list, server_default="[]")

    @declared_attr
    def gf_tag_count(cls) -> Mapped[int]:  # noqa: N805
        return mapped_column(
            Integer, nullable=False, default=0, server_default="0", index=True,
        )

    #: When the GF classifier last ran for this row (NULL = never classified).
    gf_classified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
