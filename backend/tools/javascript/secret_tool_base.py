"""Shared contract for JavaScript secret-discovery scanners (Phase 6.2).

Every scanner wrapper (SecretFinder, Mantra, Nuclei Exposures, and any future
tool) implements the same interface so the worker treats them uniformly and new
scanners plug in without touching the worker:

    run(...)          Execute the scanner and return a list of RawSecret.
    parse_output(txt) Turn raw CLI output into RawSecret objects.
    validate()        Raise if the tool cannot run.
    health_check()    Non-raising availability probe.

Wrappers return **structured** :class:`RawSecret` objects — never raw text. The
worker then classifies/normalizes/fingerprints/dedups them via
:mod:`tools.common.secret_utils`, so that logic lives in exactly one place.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(slots=True)
class RawSecret:
    """One secret as reported by a scanner, before canonical processing."""

    raw_type: str            # the scanner's own type label (e.g. "aws_access_key")
    value: str               # the secret value exactly as found (never masked)
    js_url: str | None = None  # the JS file URL it was found in, if known
    confidence: int = 50       # 0–100; scanner-provided or a sensible default
    extra: dict = field(default_factory=dict)  # scanner-specific metadata


class SecretToolBase(ABC):
    """Abstract base for JavaScript secret scanners."""

    def __init__(self, timeout: int = 300) -> None:
        self.timeout = timeout

    @property
    @abstractmethod
    def tool_name(self) -> str:
        """Uppercase label stored in ``discovery_tools`` (e.g. ``SECRETFINDER``)."""
        ...

    @abstractmethod
    def validate(self) -> None:
        """Raise :class:`RuntimeError` if the tool is not runnable."""
        ...

    @abstractmethod
    def parse_output(self, raw_output: str) -> list[RawSecret]:
        """Parse the scanner's raw output into structured secrets."""
        ...

    def health_check(self) -> bool:
        try:
            self.validate()
            return True
        except Exception:
            return False
