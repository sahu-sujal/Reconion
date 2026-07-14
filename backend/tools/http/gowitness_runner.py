"""gowitness tool wrapper — web page screenshots.

Uses ``gowitness scan file`` to screenshot a list of live URLs. Screenshots are
written to a caller-supplied ``--screenshot-path`` and a JSONL result file gives
the url → filename mapping (plus final URL / title / status) which we parse into
:class:`GowitnessRecord` objects.

gowitness docs: https://github.com/sensepost/gowitness
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.common.command_runner import run_command
from tools.common.tool_base import ToolBase


@dataclass
class GowitnessRecord:
    """One screenshot result from gowitness JSONL output."""
    url: str
    final_url: str | None
    title: str | None
    status_code: int | None
    file_name: str | None
    failed: bool
    failed_reason: str | None


class GowitnessRunner(ToolBase):
    """Screenshot a list of URLs with gowitness and return structured results."""

    _FALLBACKS = (
        str(Path.home() / "go" / "bin" / "gowitness"),
        "/root/go/bin/gowitness",
        "/usr/local/bin/gowitness",
    )

    def __init__(
        self,
        timeout: int = 1800,
        threads: int = 15,
        screenshot_format: str = "jpeg",
    ) -> None:
        super().__init__(timeout=timeout)
        self._threads = threads
        self._screenshot_format = screenshot_format

    @property
    def tool_name(self) -> str:
        return "gowitness"

    # ------------------------------------------------------------------
    # Binary resolution / health
    # ------------------------------------------------------------------

    @classmethod
    def _resolve_binary(cls) -> str:
        from tools.common.tool_paths import bundled_binary
        return bundled_binary("gowitness") or next(
            (p for p in cls._FALLBACKS if Path(p).is_file()), "gowitness"
        )

    def validate(self) -> bool:
        try:
            result = run_command([self._resolve_binary(), "version"], timeout=10)
            return result.returncode == 0 or "gowitness" in (
                result.stderr + result.stdout
            ).lower()
        except RuntimeError:
            return False

    def health_check(self) -> dict[str, Any]:
        try:
            binary = self._resolve_binary()
            result = run_command([binary, "version"], timeout=10)
            out = (result.stdout or result.stderr).strip()
            return {
                "tool": self.tool_name,
                "available": result.returncode == 0,
                "binary": binary,
                "version": out.splitlines()[-1] if out else "unknown",
            }
        except RuntimeError as exc:
            return {"tool": self.tool_name, "available": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Required interface
    # ------------------------------------------------------------------

    def run(self, target: str | list[str]) -> list[str]:
        """Not used for screenshots — capture() is the real entry point."""
        raise NotImplementedError("Use GowitnessRunner.capture()")

    # ------------------------------------------------------------------
    # Primary capture method
    # ------------------------------------------------------------------

    def capture(
        self,
        urls: list[str],
        screenshot_dir: Path,
    ) -> list[GowitnessRecord]:
        """Screenshot *urls*, writing images into *screenshot_dir*.

        Returns one :class:`GowitnessRecord` per probed URL (including failures).
        """
        urls = [u for u in urls if u]
        if not urls:
            return []

        screenshot_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", prefix="gowitness_in_", delete=False, encoding="utf-8"
        ) as tmp_in:
            tmp_in.write("\n".join(urls))
            input_path = Path(tmp_in.name)

        jsonl_path = screenshot_dir / "gowitness.jsonl"
        # gowitness appends JSONL output. A scan must only ingest records from
        # its own invocation; otherwise a rerun can persist stale captures from
        # an earlier scan of the same scope.
        jsonl_path.unlink(missing_ok=True)

        try:
            cmd = [
                self._resolve_binary(),
                "scan", "file",
                "-f", str(input_path),
                "-s", str(screenshot_dir),
                "--screenshot-format", self._screenshot_format,
                "--write-jsonl",
                "--write-jsonl-file", str(jsonl_path),
                "--threads", str(self._threads),
                "--timeout", "30",
            ]
            result = run_command(cmd, timeout=self.timeout)
            if result.timed_out:
                raise RuntimeError(f"gowitness timed out after {self.timeout}s")
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()
                raise RuntimeError(
                    f"gowitness exited with status {result.returncode}"
                    + (f": {detail}" if detail else "")
                )
            return self._parse_jsonl(jsonl_path)
        finally:
            input_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_jsonl(jsonl_path: Path) -> list[GowitnessRecord]:
        if not jsonl_path.is_file():
            return []
        records: list[GowitnessRecord] = []
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            file_name = obj.get("file_name") or None
            failed = bool(obj.get("failed"))
            response_code = obj.get("response_code")
            try:
                status_code = int(response_code) if response_code is not None else None
            except (TypeError, ValueError):
                status_code = None
            records.append(GowitnessRecord(
                url=obj.get("url", ""),
                final_url=obj.get("final_url") or None,
                title=obj.get("title") or None,
                status_code=status_code,
                file_name=file_name if not failed else None,
                failed=failed,
                failed_reason=obj.get("failed_reason") or None,
            ))
        return records
