from repositories.base_repository import BaseRepository

from database.models.finding import Finding


class FindingRepository(BaseRepository[Finding]):
    def __init__(self) -> None:
        super().__init__(Finding)

    def count_open_for_program(self, db, program_id):
        return self.count(db, program_id=program_id, status="NEW")
