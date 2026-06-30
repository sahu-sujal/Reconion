from repositories.base_repository import BaseRepository

from database.models.program import Program


class ProgramRepository(BaseRepository[Program]):
    def __init__(self) -> None:
        super().__init__(Program)
