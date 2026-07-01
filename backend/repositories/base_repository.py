from __future__ import annotations

import uuid
from typing import Generic, Type, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    def __init__(self, model: Type[ModelType]) -> None:
        self.model = model

    # ------------------------------------------------------------------
    # Scope guard (persistence-layer, caller-independent)
    # ------------------------------------------------------------------

    def _scope_target(self, db: Session, scope_id) -> str | None:
        """Look up a scope's registrable target (e.g. ``ortto.com``). Cached."""
        from database.models.scope import Scope

        cache = getattr(self, "_scope_target_cache", None)
        if cache is None:
            cache = self._scope_target_cache = {}
        key = str(scope_id)
        if key not in cache:
            cache[key] = db.scalar(select(Scope.target).where(Scope.id == scope_id))
        return cache[key]

    def enforce_scope(
        self, db: Session, rows: list, host_key: str = "host", url_key: str | None = None
    ) -> list:
        """Drop rows whose host is out of scope — a final safety net.

        Called by bulk upserts so an out-of-scope URL / JS file / endpoint can
        never be persisted regardless of which worker path produced it. Rows are
        assumed to share a single ``scope_id`` (they always do — one scan writes
        one scope); the scope target is looked up once per scope. The host is
        read from *host_key*, or derived from *url_key* for tables that store
        only a URL.
        """
        if not rows:
            return rows
        from tools.common.scope_filter import filter_rows_in_scope

        scope_id = rows[0].get("scope_id")
        target = self._scope_target(db, scope_id) if scope_id else None
        return filter_rows_in_scope(rows, target, host_key=host_key, url_key=url_key)

    def create(self, db: Session, **kwargs) -> ModelType:
        model = self.model(**kwargs)
        db.add(model)
        db.commit()
        db.refresh(model)
        return model

    def get(self, db: Session, id_: uuid.UUID) -> ModelType | None:
        return db.get(self.model, id_)

    def list(self, db: Session, offset: int = 0, limit: int = 100, **filters) -> list[ModelType]:
        statement = select(self.model)
        if filters:
            statement = statement.filter_by(**filters)
        statement = statement.offset(offset).limit(limit)
        return db.scalars(statement).all()

    def update(self, db: Session, db_obj: ModelType, **updates) -> ModelType:
        for field, value in updates.items():
            setattr(db_obj, field, value)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def delete(self, db: Session, db_obj: ModelType) -> None:
        db.delete(db_obj)
        db.commit()

    def exists(self, db: Session, **filters) -> bool:
        statement = select(func.count()).select_from(self.model).filter_by(**filters)
        return bool(db.scalar(statement))

    def count(self, db: Session, **filters) -> int:
        statement = select(func.count()).select_from(self.model).filter_by(**filters)
        return int(db.scalar(statement) or 0)
