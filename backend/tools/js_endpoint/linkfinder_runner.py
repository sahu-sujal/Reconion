"""LinkFinder wrapper — JavaScript endpoint extraction (Phase 6.1).

LinkFinder (https://github.com/GerbenJavado/LinkFinder) is a Python script that
regex-scans JavaScript for endpoints. We drive its ``-o cli`` mode, which prints
one raw endpoint per line to stdout, over already-downloaded local files.

Invocation (per file, so one malformed file never aborts the batch)::

    python3 linkfinder.py -i <file.js> -o cli

The script path is resolved from ``LINKFINDER_PATH`` (env) or a small set of
conventional locations so the wrapper works regardless of how the worker was
launched. Returns *raw* endpoint strings — resolution/normalization is done by
the worker.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tools.common.tool_paths import bundled_script
from tools.js_endpoint.endpoint_tool_base import EndpointToolBase


def _resolve_script() -> str | None:
    """Resolve linkfinder.py: env override → bundled tools/ → conventional dirs."""
    override = os.getenv("LINKFINDER_PATH", "")
    if override and Path(override).is_file():
        return override
    bundled = bundled_script("LinkFinder", "linkfinder.py")
    if bundled:
        return bundled
    for candidate in (
        str(Path.home() / "tools" / "LinkFinder" / "linkfinder.py"),
        "/opt/LinkFinder/linkfinder.py",
        "/usr/local/share/LinkFinder/linkfinder.py",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


class LinkFinderRunner(EndpointToolBase):
    """Extract endpoints from local JS files using LinkFinder."""

    def __init__(self, timeout: int = 120) -> None:
        super().__init__(timeout=timeout)
        self._script = _resolve_script()

    @property
    def tool_name(self) -> str:
        return "LINKFINDER"

    def validate(self) -> None:
        if not self._script:
            raise RuntimeError(
                "LinkFinder not found — set LINKFINDER_PATH to linkfinder.py "
                "or clone it to ~/tools/LinkFinder"
            )

    def parse_output(self, raw_output: str) -> list[str]:
        """LinkFinder ``-o cli`` prints one raw endpoint per line."""
        return self._clean_lines(raw_output)

    def run(self, js_paths: list[Path]) -> list[str]:
        """Run LinkFinder over each JS file; aggregate raw endpoint strings."""
        self.validate()
        assert self._script is not None

        endpoints: set[str] = set()
        for js_path in js_paths:
            if not js_path.is_file() or js_path.stat().st_size == 0:
                continue
            try:
                proc = subprocess.run(
                    ["python3", self._script, "-i", str(js_path), "-o", "cli"],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                # A single slow file must not sink the whole batch.
                continue
            except FileNotFoundError as exc:
                raise RuntimeError(f"python3 not found while running LinkFinder: {exc}")
            endpoints.update(self.parse_output(proc.stdout))
        return sorted(endpoints)
