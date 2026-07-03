"""Shared contract for active parameter-discovery tools (Phase 6.4).

Every wrapper (Arjun, ParamSpider, and any future tool — ParamMiner, custom
dictionaries, an AI parameter module) implements the same interface so the
Parameter Discovery worker treats them uniformly and a new tool plugs in without
touching the worker or the schema:

    run(targets)      Execute the tool over target URLs; return list[RawParameter].
    parse_output(txt) Turn raw CLI/file output into RawParameter objects.
    validate()        Raise RuntimeError if the tool cannot run.
    health_check()    Non-raising availability probe.

Wrappers return **structured** :class:`RawParameter` objects — never raw text.
The worker then normalizes / classifies / deduplicates them via
:mod:`tools.common.parameter_utils`, so that logic lives in exactly one place.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(slots=True)
class RawParameter:
    """One parameter as reported by a tool, before canonical processing."""

    name: str                 # the parameter name exactly as the tool reported it
    asset_url: str | None = None  # the URL the parameter was found on, if known
    confidence: int = 50          # 0–100; tool-provided or a sensible default
    extra: dict = field(default_factory=dict)  # tool-specific metadata


class ParameterToolBase(ABC):
    """Abstract base for active parameter-discovery tools."""

    def __init__(self, timeout: int = 300) -> None:
        self.timeout = timeout

    @property
    @abstractmethod
    def tool_name(self) -> str:
        """Uppercase label stored in ``discovery_tools`` (e.g. ``ARJUN``)."""
        ...

    @abstractmethod
    def validate(self) -> None:
        """Raise :class:`RuntimeError` if the tool is not runnable."""
        ...

    @abstractmethod
    def parse_output(self, raw_output: str) -> list[RawParameter]:
        """Parse the tool's raw output into structured parameters."""
        ...

    @abstractmethod
    def run(self, targets: list[str]) -> list[RawParameter]:
        """Run the tool over *targets* and return structured parameters."""
        ...

    def health_check(self) -> bool:
        try:
            self.validate()
            return True
        except Exception:
            return False
