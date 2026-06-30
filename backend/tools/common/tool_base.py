from __future__ import annotations

from abc import ABC, abstractmethod


class ToolBase(ABC):
    """Abstract base for all reconnaissance tool runners.

    Subclasses must declare :attr:`tool_name` and implement :meth:`run`.
    Timeout (seconds) can be customised per instance.
    """

    def __init__(self, timeout: int = 120) -> None:
        self.timeout = timeout

    @property
    @abstractmethod
    def tool_name(self) -> str:
        """Short identifier used in logging and ToolExecution records."""
        ...

    @abstractmethod
    def run(self, target: str | list[str]) -> list[str]:
        """Execute the tool and return a deduplicated, sorted result list."""
        ...
