"""gau (getallurls) runner — historical URL discovery.

Feeds a list of hosts to ``gau`` over stdin and streams the discovered URLs
directly to a file (one URL per line) to keep memory flat on large scopes.

gau aggregates Wayback Machine, Common Crawl, AlienVault OTX and URLScan.

gau docs: https://github.com/lc/gau
"""
from __future__ import annotations

from pathlib import Path

from tools.common.command_runner import run_command_to_file
from tools.common.dedupe_utils import deduplicate_file
from tools.common.file_utils import temp_output_file
from tools.common.tool_base import ToolBase


class GauRunner(ToolBase):
    """Discover historical URLs for a set of hosts via gau."""

    def __init__(self, timeout: int = 1800, threads: int = 10) -> None:
        super().__init__(timeout=timeout)
        self._threads = threads

    @property
    def tool_name(self) -> str:
        return "gau"

    def run(self, target: str | list[str]) -> list[str]:  # type: ignore[override]
        """Return a deduplicated, sorted list of discovered URLs."""
        with temp_output_file(prefix="gau_") as out_path:
            self.run_to_file(target, out_path)
            return deduplicate_file(out_path)

    def run_to_file(self, target: str | list[str], out_path: Path) -> int:
        """Stream discovered URLs to *out_path*. Returns the raw line count."""
        hosts = [target] if isinstance(target, str) else list(target)
        if not hosts:
            out_path.write_text("", encoding="utf-8")
            return 0

        cmd = [
            "gau",
            "--threads", str(self._threads),
            "--subs",
            "--providers", "wayback,commoncrawl,otx,urlscan",
        ]
        result = run_command_to_file(
            cmd,
            timeout=self.timeout,
            stdout_path=out_path,
            stdin_data="\n".join(hosts) + "\n",
        )
        if result.timed_out:
            raise RuntimeError(f"gau timed out after {self.timeout}s")
        if not out_path.exists():
            out_path.write_text("", encoding="utf-8")
            return 0
        return sum(1 for _ in out_path.open("r", encoding="utf-8", errors="replace"))
