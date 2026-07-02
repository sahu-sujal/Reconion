"""Nuclei Exposures wrapper — JavaScript secret discovery (Phase 6.2).

Nuclei (https://github.com/projectdiscovery/nuclei) is used here **only** as a
secret-discovery engine, restricted to the ``http/exposures/`` template set. It
is NOT used for vulnerability scanning in this phase — no other templates run.

    cat alljs.txt | nuclei -t <templates>/http/exposures/ -jsonl -silent

Nuclei fetches the JS URLs itself and emits JSONL. Each match carries
``matched-at`` (the JS URL), ``template-id`` / ``info.name`` (→ secret type) and
``extracted-results`` (the actual secret values). The wrapper returns
**structured** :class:`RawSecret` objects.

The exposures template directory is resolved from ``nuclei-templates/http/exposures``
in the repo root (or ``NUCLEI_EXPOSURES_PATH``).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from tools.common.command_runner import run_command
from tools.common.tool_paths import repo_root, resolve_tool
from tools.javascript.secret_tool_base import RawSecret, SecretToolBase


def _resolve_templates() -> str | None:
    for c in (
        os.getenv("NUCLEI_EXPOSURES_PATH", ""),
        str(repo_root() / "nuclei-templates" / "http" / "exposures"),
        str(Path.home() / "nuclei-templates" / "http" / "exposures"),
    ):
        if c and Path(c).is_dir():
            return c
    return None


class NucleiExposuresRunner(SecretToolBase):
    """Discover exposed secrets in JS URLs using Nuclei http/exposures templates."""

    def __init__(self, timeout: int = 1800, concurrency: int = 25, rate_limit: int = 150) -> None:
        super().__init__(timeout=timeout)
        self._bin = resolve_tool("nuclei")
        self._templates = _resolve_templates()
        self._concurrency = max(1, concurrency)
        self._rate_limit = max(1, rate_limit)

    @property
    def tool_name(self) -> str:
        return "NUCLEI_EXPOSURES"

    def validate(self) -> None:
        import shutil

        if not (Path(self._bin).is_file() or shutil.which(self._bin)):
            raise RuntimeError("nuclei not found — bundle it under tools/bin or install it")
        if not self._templates:
            raise RuntimeError(
                "nuclei http/exposures templates not found — place nuclei-templates "
                "in the repo root or set NUCLEI_EXPOSURES_PATH"
            )

    def parse_output(self, raw_output: str) -> list[RawSecret]:
        """Parse Nuclei JSONL; one RawSecret per extracted value (or per match).

        ``raw_type`` is taken from the template id / name so the worker can map
        it to a canonical type; ``extracted-results`` provides the actual values.
        """
        secrets: list[RawSecret] = []
        for line in raw_output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            js_url = obj.get("matched-at") or obj.get("url")
            info = obj.get("info") or {}
            raw_type = obj.get("template-id") or info.get("name") or "exposure"
            extracted = obj.get("extracted-results") or []
            if isinstance(extracted, list) and extracted:
                for value in extracted:
                    v = str(value).strip()
                    if v:
                        secrets.append(RawSecret(
                            raw_type=raw_type, value=v, js_url=js_url, confidence=80,
                            extra={"template_id": obj.get("template-id")},
                        ))
            else:
                # No extracted value — record the match itself (URL as the value).
                if js_url:
                    secrets.append(RawSecret(
                        raw_type=raw_type, value=js_url, js_url=js_url, confidence=60,
                        extra={"template_id": obj.get("template-id"), "match_only": True},
                    ))
        return secrets

    def run(self, js_urls: list[str]) -> list[RawSecret]:
        """Run Nuclei http/exposures over the given JS URLs (fed on stdin)."""
        self.validate()
        urls = [u for u in js_urls if u]
        if not urls:
            return []
        cmd = [
            self._bin,
            "-t", self._templates,   # http/exposures ONLY — no other templates
            "-jsonl",
            "-silent",
            "-nc",                    # no color
            "-c", str(self._concurrency),
            "-rate-limit", str(self._rate_limit),
            "-disable-update-check",
        ]
        result = run_command(cmd, timeout=self.timeout, stdin_data="\n".join(urls) + "\n")
        if result.timed_out:
            raise RuntimeError(f"nuclei timed out after {self.timeout}s")
        return self.parse_output(result.stdout)
