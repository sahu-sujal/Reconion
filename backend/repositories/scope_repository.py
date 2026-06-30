from repositories.base_repository import BaseRepository

from database.models.scope import Scope


class ScopeRepository(BaseRepository[Scope]):
    def __init__(self) -> None:
        super().__init__(Scope)
