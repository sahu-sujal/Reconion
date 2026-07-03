"""Arjun wrapper — active HTTP parameter discovery (Phase 6.4).

Arjun (https://github.com/s0md3v/Arjun) probes a URL with a wordlist and returns
the parameters the server actually reflects/accepts. It is fed a list of target
URLs (one per line via ``-i``) and writes a JSON report via ``-oJ`` mapping each
URL to the parameters it found::

    {
        "https://api.tesla.com/v1/user": {"params": ["id", "page", "sort"], ...},
        ...
    }

Arjun sends real HTTP requests, so the worker only ever hands it **dynamic**
assets (APIs, dynamic pages, auth/admin, …) already filtered by the Asset
Classification Engine — never static resources.

The wrapper returns structured :class:`RawParameter` objects; the worker
normalizes / classifies / dedups via :mod:`tools.common.parameter_utils`.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from tools.common.command_runner import run_command
from tools.common.tool_paths import resolve_tool
from tools.parameters.parameter_tool_base import ParameterToolBase, RawParameter


class ArjunRunner(ParameterToolBase):
    """Discover accepted HTTP parameters on target URLs using Arjun."""

    def __init__(
        self,
        timeout: int = 600,
        threads: int | None = None,
        stable: bool = False,
    ) -> None:
        super().__init__(timeout=timeout)
        # Arjun ships as a Python console script; fall back to `arjun` on PATH.
        self._bin = resolve_tool("arjun")
        if threads is None:
            threads = int(os.getenv("ARJUN_THREADS", "10"))
        self._threads = max(1, threads)
        # `--stable` trades speed for fewer false positives; env-tunable.
        self._stable = stable or os.getenv("ARJUN_STABLE", "").lower() in ("1", "true")

    @property
    def tool_name(self) -> str:
        return "ARJUN"

    def validate(self) -> None:
        import shutil

        if not (Path(self._bin).is_file() or shutil.which(self._bin)):
            raise RuntimeError(
                "arjun not found — install it (pipx install arjun / "
                "pip install arjun) or place it on PATH"
            )

    def parse_output(self, raw_output: str) -> list[RawParameter]:
        """Parse Arjun's JSON report (``-oJ``) into structured parameters.

        Arjun's JSON is ``{url: {"params": [...], "method": ..., ...}}`` (newer
        versions) or ``{url: [param, ...]}`` (older). Both shapes are handled.
        """
        if not raw_output.strip():
            return []
        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError:
            return []
        return list(self._iter_params(data))

    @staticmethod
    def _iter_params(data: object):
        if not isinstance(data, dict):
            return
        for url, value in data.items():
            asset_url = url if isinstance(url, str) else None
            names: list[str] = []
            if isinstance(value, dict):
                raw = value.get("params")
                if isinstance(raw, list):
                    names = [str(p) for p in raw]
                elif isinstance(raw, dict):
                    names = [str(p) for p in raw.keys()]
            elif isinstance(value, list):
                names = [str(p) for p in value]
            for name in names:
                if name:
                    yield RawParameter(name=name, asset_url=asset_url, confidence=80)

    def run(self, targets: list[str]) -> list[RawParameter]:
        """Run Arjun over *targets* (a batch of dynamic URLs).

        Writes the targets to a temp input file and reads Arjun's JSON report
        from a temp output file — both cleaned up before returning.
        """
        self.validate()
        urls = [u for u in targets if u]
        if not urls:
            return []

        with tempfile.TemporaryDirectory(prefix="arjun_") as tmp:
            in_path = Path(tmp) / "targets.txt"
            out_path = Path(tmp) / "arjun_out.json"
            in_path.write_text("\n".join(urls) + "\n", encoding="utf-8")

            cmd = [
                self._bin,
                "-i", str(in_path),
                "-oJ", str(out_path),
                "-t", str(self._threads),
            ]
            if self._stable:
                cmd.append("--stable")

            result = run_command(cmd, timeout=self.timeout)
            if result.timed_out:
                raise RuntimeError(f"arjun timed out after {self.timeout}s")

            if not out_path.is_file():
                return []
            try:
                raw = out_path.read_text(encoding="utf-8")
            except OSError:
                return []
            return self.parse_output(raw)
