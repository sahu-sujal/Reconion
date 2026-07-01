"""Shared contract for JavaScript endpoint-extraction tools (Phase 6.1).

Every extractor wrapper (LinkFinder, XNLinkFinder, and future JSluice / Mantra /
AST parsers) implements the same four-method interface so the worker treats them
uniformly and new tools plug in without touching the worker:

    run(js_paths) -> list[str]   Execute the tool over local JS files, returning
                                 the raw endpoint strings it emitted.
    parse_output(text) -> list[str]
                                 Turn the tool's raw output into a clean list of
                                 candidate endpoint strings. Workers must never
                                 parse raw tool output themselves.
    validate() -> None           Raise if the tool cannot run (binary/script
                                 missing). Called before a batch.
    health_check() -> bool       Non-raising liveness probe for diagnostics.

The wrappers deliberately return *raw* (still-relative) endpoint strings — URL
resolution and normalization are the worker's job via
:mod:`tools.common.endpoint_utils`, so resolution logic lives in exactly one
place regardless of which extractor produced the hit.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class EndpointToolBase(ABC):
    """Abstract base for JavaScript endpoint extractors."""

    def __init__(self, timeout: int = 120) -> None:
        self.timeout = timeout

    @property
    @abstractmethod
    def tool_name(self) -> str:
        """Uppercase label stored in ``discovery_tools`` (e.g. ``LINKFINDER``)."""
        ...

    @abstractmethod
    def run(self, js_paths: list[Path]) -> list[str]:
        """Extract raw endpoint strings from the given local JS files."""
        ...

    @abstractmethod
    def parse_output(self, raw_output: str) -> list[str]:
        """Parse the tool's raw output into candidate endpoint strings."""
        ...

    @abstractmethod
    def validate(self) -> None:
        """Raise :class:`RuntimeError` if the tool is not runnable."""
        ...

    def health_check(self) -> bool:
        """Return ``True`` if the tool is available, ``False`` otherwise."""
        try:
            self.validate()
            return True
        except Exception:
            return False

    @staticmethod
    def _clean_lines(raw_output: str) -> list[str]:
        """Split raw output into non-empty, de-duplicated, stripped lines."""
        seen: set[str] = set()
        out: list[str] = []
        for line in raw_output.splitlines():
            value = line.strip()
            if value and value not in seen:
                seen.add(value)
                out.append(value)
        return out
