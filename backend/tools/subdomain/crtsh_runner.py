from __future__ import annotations

import time

from tools.common.command_runner import run_command
from tools.common.dedupe_utils import deduplicate
from tools.common.tool_base import ToolBase


class CrtshRunner(ToolBase):
    """Query crt.sh certificate transparency logs via the crtsh Go binary.

    Binary: github.com/soerlemans/crtsh (`go install .../crtsh@latest`).

    Runs: crtsh -q DOMAIN
      -q  query string (the target domain); subdomains print to stdout,
          one per line, by default.

    NOTE: in this tool `-o` means "write to output file", so it must NOT
    be passed. The binary resolves through PATH (~/go/bin is prepended in
    command_runner), the same way the chaos runner locates its tool.

    crt.sh frequently rate-limits / returns a 502 HTML page instead of
    JSON. When that happens the binary logs `invalid character '<'` and
    exits 0 with no domains, so we retry a few times.
    """

    #: crt.sh is flaky; retry when an attempt yields nothing.
    MAX_ATTEMPTS = 6
    RETRY_DELAY = 5.0

    @property
    def tool_name(self) -> str:
        return "crtsh"

    def run(self, target: str) -> list[str]:  # type: ignore[override]
        subdomains: list[str] = []

        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            result = run_command(
                ["crtsh", "-q", target],
                timeout=self.timeout,
            )
            if result.timed_out:
                raise RuntimeError(f"crtsh timed out after {self.timeout}s")

            for line in result.stdout.splitlines():
                name = line.strip().lower()
                if name.startswith("*."):
                    name = name[2:]
                if name and "." in name:
                    subdomains.append(name)

            if subdomains:
                break
            if attempt < self.MAX_ATTEMPTS:
                time.sleep(self.RETRY_DELAY)

        return deduplicate(subdomains)
