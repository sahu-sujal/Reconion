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
