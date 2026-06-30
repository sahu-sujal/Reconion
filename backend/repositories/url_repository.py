from repositories.base_repository import BaseRepository

from database.models.url import URL


class URLRepository(BaseRepository[URL]):
    def __init__(self) -> None:
        super().__init__(URL)
