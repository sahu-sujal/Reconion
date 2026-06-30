from __future__ import annotations

from tools.common.command_runner import run_command
from tools.common.dedupe_utils import deduplicate
from tools.common.tool_base import ToolBase


class CrtshRunner(ToolBase):
    """Query crt.sh certificate transparency logs via the crtsh Go binary.

    Runs: crtsh -q DOMAIN -o
      -q  query string (the target domain)
      -o  print only domains (one per line on stdout)

    The binary is resolved through PATH (~/go/bin is prepended in
    command_runner), the same way the chaos runner locates its tool.
    """

    @property
    def tool_name(self) -> str:
        return "crtsh"

    def run(self, target: str) -> list[str]:  # type: ignore[override]
        result = run_command(
            ["crtsh", "-q", target, "-o"],
            timeout=self.timeout,
        )
        if result.timed_out:
            raise RuntimeError(f"crtsh timed out after {self.timeout}s")

        subdomains: list[str] = []
        for line in result.stdout.splitlines():
            name = line.strip().lower()
            if name.startswith("*."):
                name = name[2:]
            if name and "." in name:
                subdomains.append(name)

        return deduplicate(subdomains)
