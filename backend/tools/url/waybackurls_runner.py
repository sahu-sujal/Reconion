"""waybackurls runner — historical URL discovery from the Wayback Machine.

Reads hosts from stdin (one per line) and streams discovered URLs to a file.

waybackurls docs: https://github.com/tomnomnom/waybackurls
"""
from __future__ import annotations

from pathlib import Path

from tools.common.command_runner import run_command_to_file
from tools.common.dedupe_utils import deduplicate_file
from tools.common.file_utils import temp_output_file
from tools.common.tool_base import ToolBase


class WaybackurlsRunner(ToolBase):
    """Discover historical URLs for a set of hosts via waybackurls."""

    def __init__(self, timeout: int = 1800) -> None:
        super().__init__(timeout=timeout)

    @property
    def tool_name(self) -> str:
        return "waybackurls"

    def run(self, target: str | list[str]) -> list[str]:  # type: ignore[override]
        with temp_output_file(prefix="waybackurls_") as out_path:
            self.run_to_file(target, out_path)
            return deduplicate_file(out_path)

    def run_to_file(self, target: str | list[str], out_path: Path) -> int:
        """Stream discovered URLs to *out_path*. Returns the raw line count."""
        hosts = [target] if isinstance(target, str) else list(target)
        if not hosts:
            out_path.write_text("", encoding="utf-8")
            return 0

        result = run_command_to_file(
            ["waybackurls"],
            timeout=self.timeout,
            stdout_path=out_path,
            stdin_data="\n".join(hosts) + "\n",
        )
        if result.timed_out:
            raise RuntimeError(f"waybackurls timed out after {self.timeout}s")
        if not out_path.exists():
            out_path.write_text("", encoding="utf-8")
            return 0
        return sum(1 for _ in out_path.open("r", encoding="utf-8", errors="replace"))
