from repositories.base_repository import BaseRepository

from database.models.program_settings import ProgramSettings


class ProgramSettingsRepository(BaseRepository[ProgramSettings]):
    def __init__(self) -> None:
        super().__init__(ProgramSettings)
