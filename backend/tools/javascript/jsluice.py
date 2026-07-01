"""JSluice wrapper — AST-based JavaScript endpoint extraction (Phase 6.1).

JSluice (https://github.com/BishopFox/jsluice) parses JavaScript into an abstract
syntax tree and extracts URLs/paths that regex tools miss — endpoints hidden
behind variable concatenation, template literals, object references and dynamic
string construction::

    const API = "/api"; const V = "/v1";
    fetch(API + V + "/users");     // -> /api/v1/users

We drive ``jsluice urls`` mode, which emits **newline-delimited JSON**, one
object per discovered URL::

    {"url":"/api/v1/users","queryParams":[],"method":"","type":"fetch",...}

The wrapper returns **structured** :class:`JsluiceEndpoint` objects (never raw
text) so the worker consumes JSluice identically to every other extractor. Final
resolution against the originating JS URL and normalization remain the worker's
job, so resolution logic lives in exactly one place.

This wrapper performs endpoint extraction ONLY. JSluice's ``secrets`` mode is
deliberately never invoked here.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from tools.common.tool_paths import bundled_binary
from tools.js_endpoint.endpoint_tool_base import EndpointToolBase


def _resolve_bin() -> str | None:
    """Resolve jsluice: env override → bundled tools/bin → PATH → ~/go/bin."""
    override = os.getenv("JSLUICE_PATH", "")
    if override and Path(override).is_file():
        return override
    bundled = bundled_binary("jsluice")
    if bundled:
        return bundled
    for candidate in (
        shutil.which("jsluice") or "",
        str(Path.home() / "go" / "bin" / "jsluice"),
        "/usr/local/bin/jsluice",
    ):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


@dataclass(slots=True)
class JsluiceEndpoint:
    """One structured endpoint extracted by JSluice."""

    url: str                       # raw or JSluice-resolved URL/path
    method: str = ""               # HTTP method when JSluice inferred one
    node_type: str = ""            # JSluice "type" (fetch, axios.get, stringLiteral…)
    query_params: list[str] = field(default_factory=list)
    filename: str | None = None    # local file JSluice read it from


class JsluiceRunner(EndpointToolBase):
    """Extract endpoints from local JS files using JSluice AST analysis."""

    def __init__(self, timeout: int = 300, concurrency: int = 4) -> None:
        super().__init__(timeout=timeout)
        self._bin = _resolve_bin()
        self._concurrency = max(1, concurrency)

    @property
    def tool_name(self) -> str:
        return "JSLUICE"

    def validate(self) -> None:
        if not self._bin:
            raise RuntimeError(
                "jsluice not found — install it (go install "
                "github.com/BishopFox/jsluice/cmd/jsluice@latest) or set JSLUICE_PATH"
            )

    # ------------------------------------------------------------------
    # Structured parsing (workers never parse raw JSluice output)
    # ------------------------------------------------------------------

    def parse_output(self, raw_output: str) -> list[JsluiceEndpoint]:
        """Parse JSluice's newline-delimited JSON into structured objects.

        Malformed lines are skipped so a single bad record never discards the
        rest of a file's results.
        """
        endpoints: list[JsluiceEndpoint] = []
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
            url = obj.get("url")
            if not url or not isinstance(url, str):
                continue
            qp = obj.get("queryParams") or []
            endpoints.append(
                JsluiceEndpoint(
                    url=url.strip(),
                    method=str(obj.get("method") or ""),
                    node_type=str(obj.get("type") or ""),
                    query_params=[str(p) for p in qp] if isinstance(qp, list) else [],
                    filename=obj.get("filename"),
                )
            )
        return endpoints

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(self, js_paths: list[Path]) -> list[JsluiceEndpoint]:
        """Run JSluice over the given local JS files in a single concurrent pass.

        JSluice accepts many files at once and parallelises internally via
        ``-c``, so we hand it the whole batch. Returns structured endpoints.
        """
        self.validate()
        assert self._bin is not None

        existing = [str(p) for p in js_paths if p.is_file() and p.stat().st_size > 0]
        if not existing:
            return []

        cmd = [self._bin, "urls", "-c", str(self._concurrency), *existing]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"jsluice timed out after {self.timeout}s")
        except FileNotFoundError as exc:
            raise RuntimeError(f"jsluice binary not runnable: {exc}")

        return self.parse_output(proc.stdout)

    def run_single(self, js_path: Path) -> list[JsluiceEndpoint]:
        """Run JSluice over one file (used for per-file retry on batch failure)."""
        return self.run([js_path])
