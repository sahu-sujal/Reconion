from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import tools.common.command_runner  # ensure ~/go/bin is on PATH
from tools.common.dedupe_utils import deduplicate_file
from tools.common.tool_base import ToolBase


class DnsgenRunner(ToolBase):
    """Generate subdomain permutations using dnsgen.

    Pipes ``echo DOMAIN | dnsgen -`` and captures stdout to a temp file.
    """

    @property
    def tool_name(self) -> str:
        return "dnsgen"

    def run(self, target: str) -> list[str]:  # type: ignore[override]
        fd, path_str = tempfile.mkstemp(prefix="dnsgen_", suffix=".txt")
        out_path = Path(path_str)
        try:
            import os
            os.close(fd)

            try:
                with out_path.open("w", encoding="utf-8") as fout:
                    proc = subprocess.run(
                        ["dnsgen", "-"],
                        input=target,
                        stdout=fout,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=self.timeout,
                        check=False,
                    )
            except subprocess.TimeoutExpired:
                raise RuntimeError(f"dnsgen timed out after {self.timeout}s")
            except FileNotFoundError:
                raise RuntimeError("'dnsgen' not found — is it installed and on PATH?")

            return deduplicate_file(out_path)
        finally:
            out_path.unlink(missing_ok=True)
