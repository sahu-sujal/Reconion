"""Subjs wrapper — JavaScript file discovery (Phase 5, Content Discovery).

Subjs (https://github.com/lc/subjs) fetches live hosts and extracts the URLs of
the JavaScript files they reference (``<script src>``, inline imports, etc.). It
is a **discovery** tool only — it finds *which* JS files exist; it does not parse
them. Endpoint extraction, secrets and analysis belong to Phase 6.

CLI: reads seed URLs from stdin (or ``-i <file>``) and prints discovered JS file
URLs to stdout, one per line::

    cat live_hosts.txt | subjs -c 20 -t 15

The wrapper exposes the standard endpoint-tool interface and returns **structured**
:class:`SubjsResult` objects (never raw text). Normalization / deduplication /
persistence are the worker's job, so that logic lives in exactly one place.

Large scopes: hosts are streamed to disk in batches (``run_to_file``) so the full
set never sits in memory, and failed batches are retried a bounded number of
times before being given up on.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from tools.common.command_runner import run_command_to_file
from tools.common.file_utils import write_lines_to_tempfile
from tools.common.tool_paths import bundled_binary
from tools.js_endpoint.endpoint_tool_base import EndpointToolBase

_SUBJS_BIN_CANDIDATES = (
    os.getenv("SUBJS_PATH", ""),
    shutil.which("subjs") or "",
    str(Path.home() / "go" / "bin" / "subjs"),
    "/usr/local/bin/subjs",
)


def _resolve_bin() -> str | None:
    """Resolve subjs: repo-bundled tools/bin first, then env/PATH/go-bin."""
    bundled = bundled_binary("subjs")
    if bundled:
        return bundled
    for candidate in _SUBJS_BIN_CANDIDATES:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


@dataclass(slots=True)
class SubjsResult:
    """Structured result of a Subjs run."""

    js_urls: list[str] = field(default_factory=list)  # discovered JS file URLs
    hosts_processed: int = 0                           # live hosts fed to subjs


class SubjsRunner(EndpointToolBase):
    """Discover JavaScript file URLs from live hosts using Subjs."""

    def __init__(self, timeout: int = 1800, concurrency: int = 20, http_timeout: int = 15) -> None:
        super().__init__(timeout=timeout)
        self._bin = _resolve_bin()
        self._concurrency = max(1, concurrency)
        self._http_timeout = max(1, http_timeout)

    @property
    def tool_name(self) -> str:
        return "SUBJS"

    def validate(self) -> None:
        if not self._bin:
            raise RuntimeError(
                "subjs not found — bundle it under tools/bin, install it "
                "(go install github.com/lc/subjs@latest), or set SUBJS_PATH"
            )

    # ------------------------------------------------------------------
    # Structured parsing (workers never parse raw CLI output)
    # ------------------------------------------------------------------

    def parse_output(self, raw_output: str) -> list[str]:
        """Parse Subjs stdout (one JS URL per line) into a clean, deduped list.

        Only http(s) JS URLs are kept; blank lines and non-URL noise are dropped.
        """
        seen: set[str] = set()
        out: list[str] = []
        for line in raw_output.splitlines():
            value = line.strip()
            if not value or not value.lower().startswith(("http://", "https://")):
                continue
            if value not in seen:
                seen.add(value)
                out.append(value)
        return out

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(self, live_urls: list[str]) -> SubjsResult:
        """Run Subjs over *live_urls* (scheme-qualified live hosts).

        Returns a :class:`SubjsResult` with the discovered JS URLs and the number
        of hosts processed. Dead hosts simply yield nothing; one host failing
        never aborts the run.
        """
        self.validate()
        hosts = [u for u in live_urls if u]
        if not hosts:
            return SubjsResult(js_urls=[], hosts_processed=0)

        raw = self._invoke(hosts)
        return SubjsResult(js_urls=self.parse_output(raw), hosts_processed=len(hosts))

    def run_to_file(self, live_urls: list[str], out_path: Path) -> int:
        """Stream discovered JS URLs to *out_path* (memory-flat). Returns raw count.

        Used by the worker for large scopes so the raw ``subjs.json`` artifact is
        written directly to disk. Retries the batch a bounded number of times on
        transient failure before giving up.
        """
        self.validate()
        hosts = [u for u in live_urls if u]
        if not hosts:
            out_path.write_text("", encoding="utf-8")
            return 0

        list_path = write_lines_to_tempfile(hosts, suffix=".txt")
        try:
            cmd = [
                self._bin,
                "-i", str(list_path),
                "-c", str(self._concurrency),
                "-t", str(self._http_timeout),
            ]
            last_err: Exception | None = None
            for attempt in range(3):  # bounded retry on transient failure
                result = run_command_to_file(cmd, timeout=self.timeout, stdout_path=out_path)
                if result.timed_out:
                    last_err = RuntimeError(f"subjs timed out after {self.timeout}s")
                    continue
                if not out_path.exists():
                    out_path.write_text("", encoding="utf-8")
                    return 0
                return sum(1 for _ in out_path.open("r", encoding="utf-8", errors="replace"))
            raise last_err or RuntimeError("subjs failed")
        finally:
            list_path.unlink(missing_ok=True)

    def _invoke(self, hosts: list[str]) -> str:
        """Run subjs feeding *hosts* on stdin; return raw stdout."""
        from tools.common.command_runner import run_command

        cmd = [
            self._bin,
            "-c", str(self._concurrency),
            "-t", str(self._http_timeout),
        ]
        result = run_command(
            cmd, timeout=self.timeout, stdin_data="\n".join(hosts) + "\n",
        )
        if result.timed_out:
            raise RuntimeError(f"subjs timed out after {self.timeout}s")
        return result.stdout
