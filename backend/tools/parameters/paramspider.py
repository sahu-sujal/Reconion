"""ParamSpider wrapper — passive parameter discovery (Phase 6.4).

ParamSpider (https://github.com/devanshbatham/ParamSpider) mines archived URLs
(Wayback) for a domain and emits every URL that carries query parameters, with
each value replaced by a ``FUZZ`` placeholder, e.g.::

    https://tesla.com/search?q=FUZZ&page=FUZZ

ParamSpider is invoked **per in-scope domain** (``-d``) — the worker derives the
set of domains from the classified dynamic assets it is routing, so ParamSpider
only ever runs for hosts that already have dynamic assets in the inventory (it
does not re-crawl or re-run Phase-5 collectors). The wrapper parses the emitted
URLs, extracts the parameter names, and attributes each to its originating URL.

Returns structured :class:`RawParameter` objects; the worker normalizes /
classifies / dedups via :mod:`tools.common.parameter_utils`.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from tools.common.command_runner import run_command
from tools.common.tool_paths import resolve_tool
from tools.parameters.parameter_tool_base import ParameterToolBase, RawParameter


class ParamSpiderRunner(ParameterToolBase):
    """Discover parameters from archived URLs for a domain using ParamSpider."""

    def __init__(self, timeout: int = 600, level: int | None = None) -> None:
        super().__init__(timeout=timeout)
        self._bin = resolve_tool("paramspider")
        # Crawl "level" controls subdomain inclusion; env-tunable.
        self._level = level if level is not None else int(os.getenv("PARAMSPIDER_LEVEL", "2"))

    @property
    def tool_name(self) -> str:
        return "PARAMSPIDER"

    def validate(self) -> None:
        import shutil

        if not (Path(self._bin).is_file() or shutil.which(self._bin)):
            raise RuntimeError(
                "paramspider not found — install it "
                "(pipx install paramspider / pip install paramspider) or place it on PATH"
            )

    def parse_output(self, raw_output: str) -> list[RawParameter]:
        """Parse ParamSpider's URL list (one URL per line, values = ``FUZZ``).

        Each line is a URL like ``https://host/path?a=FUZZ&b=FUZZ``; we split the
        query string and emit one :class:`RawParameter` per parameter name,
        attributed to that URL.
        """
        params: list[RawParameter] = []
        for line in raw_output.splitlines():
            url = line.strip()
            if not url or "?" not in url:
                continue
            try:
                query = urlsplit(url).query
            except ValueError:
                continue
            if not query:
                continue
            # keep_blank_values so ``a=FUZZ&b`` still yields ``b``.
            for name, _value in parse_qsl(query, keep_blank_values=True):
                if name:
                    params.append(RawParameter(name=name, asset_url=url, confidence=60))
        return params

    def run(self, targets: list[str]) -> list[RawParameter]:
        """Run ParamSpider for the domains present in *targets*.

        *targets* are dynamic asset URLs (routed by the classifier). ParamSpider
        works per-domain, so we derive the distinct in-scope hosts from the
        targets and run it once per host, then merge the discovered parameters.
        """
        self.validate()
        domains = self._domains_of(targets)
        if not domains:
            return []

        merged: list[RawParameter] = []
        for domain in domains:
            merged.extend(self._run_domain(domain))
        return merged

    def _run_domain(self, domain: str) -> list[RawParameter]:
        with tempfile.TemporaryDirectory(prefix="paramspider_") as tmp:
            out_path = Path(tmp) / f"{domain}.txt"
            cmd = [
                self._bin,
                "-d", domain,
                "-l", str(self._level),
                "-o", str(out_path),
            ]
            result = run_command(cmd, timeout=self.timeout)
            if result.timed_out:
                raise RuntimeError(f"paramspider timed out after {self.timeout}s for {domain}")

            # Newer ParamSpider writes to the -o path; older builds default to
            # results/<domain>.txt — check both.
            candidates = [out_path, Path("results") / f"{domain}.txt"]
            for path in candidates:
                if path.is_file():
                    try:
                        raw = path.read_text(encoding="utf-8", errors="ignore")
                    except OSError:
                        continue
                    return self.parse_output(raw)
            # Some builds print to stdout instead of a file.
            return self.parse_output(result.stdout)

    @staticmethod
    def _domains_of(targets: list[str]) -> list[str]:
        """Distinct hostnames present in the target URLs (order-stable)."""
        seen: dict[str, None] = {}
        for url in targets:
            if not url:
                continue
            try:
                host = urlsplit(url).hostname
            except ValueError:
                host = None
            if host:
                seen.setdefault(host.lower(), None)
        return list(seen.keys())
