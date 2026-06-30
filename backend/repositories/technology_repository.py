from repositories.base_repository import BaseRepository

from database.models.technology import Technology


class TechnologyRepository(BaseRepository[Technology]):
    def __init__(self) -> None:
        super().__init__(Technology)
