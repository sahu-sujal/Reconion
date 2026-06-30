from __future__ import annotations

import tempfile
from pathlib import Path

from tools.common.command_runner import run_command_to_file
from tools.common.dedupe_utils import deduplicate_file
from tools.common.tool_base import ToolBase


class FindomainRunner(ToolBase):
    """Enumerate subdomains using findomain."""

    @property
    def tool_name(self) -> str:
        return "findomain"

    def run(self, target: str) -> list[str]:  # type: ignore[override]
        with tempfile.NamedTemporaryFile(prefix="findomain_", suffix=".txt") as tmp:
            path = Path(tmp.name)
            result = run_command_to_file(
                ["findomain", "-t", target, "-q"],
                timeout=self.timeout,
                stdout_path=path,
            )
            if result.timed_out:
                raise RuntimeError(f"findomain timed out after {self.timeout}s")
            return deduplicate_file(path)
