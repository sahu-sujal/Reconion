"""Mantra wrapper — JavaScript secret discovery (Phase 6.2).

Mantra (https://github.com/brosck/mantra) fetches JS URLs and greps them for
API keys / secrets. It reads URLs on stdin and prints one finding per line as
(ANSI-coloured)::

    [+] <js_url> [<secret_value>]

Mantra does not categorise the secret type — it only reports the matched value —
so the worker classifies the type from the value via
:mod:`tools.common.secret_utils`. The wrapper strips ANSI colour codes and
returns **structured** :class:`RawSecret` objects.

Because Mantra fetches the URLs itself, it is fed the stored JS URLs directly
(no local-file dependency) — matching the spec's network model.
"""
from __future__ import annotations

import re

from tools.common.command_runner import run_command
from tools.common.tool_paths import resolve_tool
from tools.javascript.secret_tool_base import RawSecret, SecretToolBase

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
# Match "[+] <url> [<value>]" (optionally followed by "[Line: N]"), post-strip.
_LINE_RE = re.compile(r"^\[\+\]\s+(\S+)\s+\[(.+?)\](?:\s+\[Line:\s*\d+\])?\s*$")


class MantraRunner(SecretToolBase):
    """Discover secrets in JS URLs using Mantra."""

    def __init__(self, timeout: int = 600, threads: int = 50) -> None:
        super().__init__(timeout=timeout)
        self._bin = resolve_tool("mantra")
        self._threads = max(1, threads)

    @property
    def tool_name(self) -> str:
        return "MANTRA"

    def validate(self) -> None:
        # resolve_tool returns the bare name as a last resort; verify a real file.
        from pathlib import Path
        import shutil

        if not (Path(self._bin).is_file() or shutil.which(self._bin)):
            raise RuntimeError(
                "mantra not found — bundle it under tools/bin, install it "
                "(go install github.com/brosck/mantra@latest), or set it on PATH"
            )

    def parse_output(self, raw_output: str) -> list[RawSecret]:
        """Parse Mantra output lines: ``[+] <url> [<value>]``.

        Mantra sometimes reports both the bare value and the surrounding
        assignment (``key = "value"``); we keep the raw value and let the worker
        classify. Type is left blank so classification is value-driven.
        """
        secrets: list[RawSecret] = []
        for line in raw_output.splitlines():
            clean = _ANSI_RE.sub("", line).strip()
            m = _LINE_RE.match(clean)
            if not m:
                continue
            js_url, value = m.group(1), m.group(2).strip()
            if not value:
                continue
            secrets.append(RawSecret(raw_type="", value=value, js_url=js_url, confidence=60))
        return secrets

    def run(self, js_urls: list[str]) -> list[RawSecret]:
        """Run Mantra over the given JS URLs (fed on stdin)."""
        self.validate()
        urls = [u for u in js_urls if u]
        if not urls:
            return []
        result = run_command(
            [self._bin, "-s", "-t", str(self._threads)],
            timeout=self.timeout,
            stdin_data="\n".join(urls) + "\n",
        )
        if result.timed_out:
            raise RuntimeError(f"mantra timed out after {self.timeout}s")
        return self.parse_output(result.stdout)
