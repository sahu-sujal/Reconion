from repositories.base_repository import BaseRepository

from database.models.notification import Notification


class NotificationRepository(BaseRepository[Notification]):
    def __init__(self) -> None:
        super().__init__(Notification)
