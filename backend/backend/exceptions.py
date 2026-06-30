from __future__ import annotations


class APIError(Exception):
    """A general API error for invalid requests."""

    def __init__(self, message: str | None = None) -> None:
        self.message = message or "Bad request"
        super().__init__(self.message)


class EntityNotFoundError(APIError):
    """Raised when a requested entity cannot be found."""

    def __init__(self, resource_name: str, identifier: str | None = None) -> None:
        payload = f"{resource_name} not found"
        if identifier is not None:
            payload = f"{resource_name} not found: {identifier}"
        super().__init__(payload)


class ScanLockedError(APIError):
    """Raised when a scope already has an active scan lock."""

    def __init__(self, scope_id: str) -> None:
        super().__init__(f"Scope scan is already in progress: {scope_id}")
