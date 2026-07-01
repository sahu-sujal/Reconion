from __future__ import annotations

import json
import subprocess
from pathlib import Path

import tools.common.command_runner  # ensure ~/go/bin is on PATH
from tools.common.dedupe_utils import deduplicate
from tools.common.tool_base import ToolBase

# Resolve knockpy explicitly so the runner works regardless of how the worker
# process was launched: the repo-bundled copy under tools/bin first, then the
# system install.
from tools.common.tool_paths import resolve_tool

_KNOCKPY_BIN = resolve_tool("knockpy", fallbacks=("/usr/bin/knockpy",))


class KnockpyRunner(ToolBase):
    """Enumerate subdomains using knockpy v9 in recon + JSON mode.

    Command: knockpy -d DOMAIN --recon --json
    Output:  JSON list printed to stdout, each entry has a "domain" key.
    """

    @property
    def tool_name(self) -> str:
        return "knockpy"

    def run(self, target: str) -> list[str]:  # type: ignore[override]
        if not Path(_KNOCKPY_BIN).exists():
            raise RuntimeError(
                f"knockpy not found at {_KNOCKPY_BIN} — is knock-subdomains installed?"
            )
        try:
            proc = subprocess.run(
                [_KNOCKPY_BIN, "-d", target, "--recon", "--json"],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"knockpy timed out after {self.timeout}s")

        return _parse_knockpy_stdout(proc.stdout)


def _parse_knockpy_stdout(stdout: str) -> list[str]:
    """Extract subdomain strings from knockpy --json stdout.

    knockpy v9 emits a JSON array where each element is an object with a
    "domain" key, e.g.:
        [{"domain": "api.example.com", "ip": [...], ...}, ...]
    """
    stdout = stdout.strip()
    if not stdout:
        return []

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        # stdout may have mixed progress lines before the JSON block —
        # find the first '[' and try from there
        bracket = stdout.find("[")
        if bracket == -1:
            return []
        try:
            data = json.loads(stdout[bracket:])
        except json.JSONDecodeError:
            return []

    if not isinstance(data, list):
        return []

    subdomains: list[str] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        value = entry.get("domain", "")
        if value and "." in value:
            subdomains.append(value.strip().lower())

    return deduplicate(subdomains)
