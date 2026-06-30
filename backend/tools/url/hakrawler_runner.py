"""hakrawler runner — active crawling of live hosts.

Reads seed URLs from stdin (one per line) and streams discovered URLs to a
file. hakrawler emits plain URLs (one per line).

hakrawler docs: https://github.com/hakluke/hakrawler
"""
from __future__ import annotations

from pathlib import Path

from tools.common.command_runner import run_command_to_file
from tools.common.dedupe_utils import deduplicate_file
from tools.common.file_utils import temp_output_file
from tools.common.tool_base import ToolBase


class HakrawlerRunner(ToolBase):
    """Crawl live hosts via hakrawler and return discovered URLs."""

    def __init__(self, timeout: int = 1800, depth: int = 3, threads: int = 10) -> None:
        super().__init__(timeout=timeout)
        self._depth = depth
        self._threads = threads

    @property
    def tool_name(self) -> str:
        return "hakrawler"

    def run(self, target: str | list[str]) -> list[str]:  # type: ignore[override]
        with temp_output_file(prefix="hakrawler_") as out_path:
            self.crawl_to_file(target, out_path)
            return deduplicate_file(out_path)

    def crawl_to_file(self, target: str | list[str], out_path: Path) -> int:
        """Crawl seeds and stream discovered URLs to *out_path*. Returns line count."""
        hosts = [target] if isinstance(target, str) else list(target)
        if not hosts:
            out_path.write_text("", encoding="utf-8")
            return 0

        cmd = [
            "hakrawler",
            "-d", str(self._depth),
            "-t", str(self._threads),
            "-u",   # show only unique urls
            "-insecure",
        ]
        result = run_command_to_file(
            cmd,
            timeout=self.timeout,
            stdout_path=out_path,
            stdin_data="\n".join(hosts) + "\n",
        )
        if result.timed_out:
            raise RuntimeError(f"hakrawler timed out after {self.timeout}s")
        if not out_path.exists():
            out_path.write_text("", encoding="utf-8")
            return 0
        return sum(1 for _ in out_path.open("r", encoding="utf-8", errors="replace"))
