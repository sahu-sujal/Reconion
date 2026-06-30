from repositories.base_repository import BaseRepository

from database.models.scan_run import ScanRun


class ScanRunRepository(BaseRepository[ScanRun]):
    def __init__(self) -> None:
        super().__init__(ScanRun)

    def get_last_finished_at(self, db, program_id):
        statement = self.model.__table__.select().where(self.model.program_id == program_id).order_by(self.model.finished_at.desc()).limit(1)
        row = db.execute(statement).first()
        return row[0] if row else None

    def get_latest_by_scope(self, db, scope_id):
        statement = (
            self.model.__table__
            .select()
            .where(self.model.scope_id == scope_id)
            .order_by(self.model.created_at.desc())
            .limit(1)
        )
        row = db.execute(statement).first()
        return self.model(**row._mapping) if row else None
