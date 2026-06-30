"""katana runner — active crawling of live hosts.

Crawls a set of live host URLs and emits discovered endpoints. We use JSONL
output so we can reliably extract the absolute endpoint for each record and
detect JavaScript assets.

katana docs: https://github.com/projectdiscovery/katana
"""
from __future__ import annotations

import json
from pathlib import Path

from tools.common.command_runner import run_command_to_file
from tools.common.file_utils import temp_output_file, write_lines_to_tempfile
from tools.common.tool_base import ToolBase


class KatanaRunner(ToolBase):
    """Crawl live hosts via katana and return discovered URLs."""

    def __init__(
        self,
        timeout: int = 1800,
        depth: int = 3,
        concurrency: int = 10,
        parallelism: int = 10,
        rate_limit: int = 150,
    ) -> None:
        super().__init__(timeout=timeout)
        self._depth = depth
        self._concurrency = concurrency
        self._parallelism = parallelism
        self._rate_limit = rate_limit

    @property
    def tool_name(self) -> str:
        return "katana"

    def run(self, target: str | list[str]) -> list[str]:  # type: ignore[override]
        """Return a deduplicated, sorted list of discovered URLs."""
        with temp_output_file(prefix="katana_") as out_path:
            self.crawl_to_file(target, out_path)
            return sorted(self._iter_endpoints(out_path))

    def crawl_to_file(self, target: str | list[str], out_path: Path) -> int:
        """Crawl and stream raw JSONL records to *out_path*. Returns line count."""
        hosts = [target] if isinstance(target, str) else list(target)
        if not hosts:
            out_path.write_text("", encoding="utf-8")
            return 0

        list_path = write_lines_to_tempfile(hosts, suffix=".txt")
        try:
            cmd = [
                "katana",
                "-list", str(list_path),
                "-jsonl",
                "-silent",
                "-depth", str(self._depth),
                "-concurrency", str(self._concurrency),
                "-parallelism", str(self._parallelism),
                "-rate-limit", str(self._rate_limit),
                "-js-crawl",          # parse JS files for additional endpoints
                "-known-files", "all",  # crawl robots.txt + sitemap.xml
                "-no-color",
            ]
            result = run_command_to_file(cmd, timeout=self.timeout, stdout_path=out_path)
            if result.timed_out:
                raise RuntimeError(f"katana timed out after {self.timeout}s")
            if not out_path.exists():
                out_path.write_text("", encoding="utf-8")
                return 0
            return sum(1 for _ in out_path.open("r", encoding="utf-8", errors="replace"))
        finally:
            list_path.unlink(missing_ok=True)

    @staticmethod
    def _iter_endpoints(path: Path) -> set[str]:
        """Extract absolute endpoint URLs from katana JSONL output."""
        endpoints: set[str] = set()
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                endpoint = KatanaRunner.extract_endpoint(line)
                if endpoint:
                    endpoints.add(endpoint)
        return endpoints

    @staticmethod
    def extract_endpoint(line: str) -> str | None:
        """Pull the endpoint URL out of one katana JSONL line.

        Handles both the nested ``{"request": {"endpoint": ...}}`` schema and a
        plain-text fallback (when katana is run without ``-jsonl``).
        """
        line = line.strip()
        if not line:
            return None
        if not line.startswith("{"):
            # Plain URL line
            return line if line.startswith(("http://", "https://")) else None
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return None
        request = obj.get("request") or {}
        endpoint = request.get("endpoint") or obj.get("endpoint")
        if isinstance(endpoint, str) and endpoint.startswith(("http://", "https://")):
            return endpoint
        return None
