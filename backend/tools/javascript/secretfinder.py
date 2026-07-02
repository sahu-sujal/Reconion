"""SecretFinder wrapper — JavaScript secret discovery (Phase 6.2).

SecretFinder (https://github.com/m4ll0k/SecretFinder) regex-scans JavaScript for
secrets/keys. We drive its ``-o cli`` mode over already-downloaded local files,
which prints one finding per line as ``<type>\\t->\\t<value>``::

    python3 SecretFinder.py -i <file.js> -o cli

The script path is resolved from the repo-bundled ``tools/SecretFinder`` (or
``SECRETFINDER_PATH``). Returns **structured** :class:`RawSecret` objects; the
worker does classification / normalization / dedup.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tools.common.tool_paths import repo_root
from tools.javascript.secret_tool_base import RawSecret, SecretToolBase

_CANDIDATE_PATHS = (
    os.getenv("SECRETFINDER_PATH", ""),
    str(repo_root() / "tools" / "SecretFinder" / "SecretFinder.py"),
    str(Path.home() / "tools" / "SecretFinder" / "SecretFinder.py"),
    "/opt/SecretFinder/SecretFinder.py",
)


def _resolve_script() -> str | None:
    for c in _CANDIDATE_PATHS:
        if c and Path(c).is_file():
            return c
    return None


class SecretFinderRunner(SecretToolBase):
    """Extract secrets from local JS files using SecretFinder."""

    def __init__(self, timeout: int = 120) -> None:
        super().__init__(timeout=timeout)
        self._script = _resolve_script()

    @property
    def tool_name(self) -> str:
        return "SECRETFINDER"

    def validate(self) -> None:
        if not self._script:
            raise RuntimeError(
                "SecretFinder not found — bundle it under tools/SecretFinder or "
                "set SECRETFINDER_PATH"
            )

    def parse_output(self, raw_output: str, js_url: str | None = None) -> list[RawSecret]:
        """Parse ``-o cli`` output: lines of ``<type>\\t->\\t<value>``."""
        secrets: list[RawSecret] = []
        for line in raw_output.splitlines():
            line = line.rstrip("\n")
            if "->" not in line:
                continue
            # Format is "type\t->\tvalue"; split on the "->" arrow.
            left, _, right = line.partition("->")
            raw_type = left.strip().strip("[]").strip()
            value = right.strip()
            if not value or not raw_type:
                continue
            secrets.append(RawSecret(raw_type=raw_type, value=value, js_url=js_url, confidence=70))
        return secrets

    def run(self, js_files: list[tuple[Path, str]]) -> list[RawSecret]:
        """Scan local JS files. *js_files* is ``[(local_path, js_url), ...]``.

        Runs SecretFinder once per file (isolating a malformed file), tagging
        each finding with its originating JS URL.
        """
        self.validate()
        assert self._script is not None
        out: list[RawSecret] = []
        for path, js_url in js_files:
            if not path.is_file() or path.stat().st_size == 0:
                continue
            try:
                proc = subprocess.run(
                    ["python3", self._script, "-i", str(path), "-o", "cli"],
                    capture_output=True, text=True, timeout=self.timeout, check=False,
                    stdin=subprocess.DEVNULL,
                )
            except subprocess.TimeoutExpired:
                continue  # one slow file must not sink the batch
            except FileNotFoundError as exc:
                raise RuntimeError(f"python3 not found while running SecretFinder: {exc}")
            out.extend(self.parse_output(proc.stdout, js_url=js_url))
        return out
