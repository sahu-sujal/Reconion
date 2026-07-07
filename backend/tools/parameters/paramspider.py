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

    def __init__(self, timeout: int = 600, level: int | None = None,
                 subs: bool = True) -> None:
        super().__init__(timeout=timeout)
        self._bin = resolve_tool("paramspider")
        # Crawl "level" controls subdomain inclusion; env-tunable.
        self._level = level if level is not None else int(os.getenv("PARAMSPIDER_LEVEL", "2"))
        # `--subs` also mines archived URLs for the domain's subdomains.
        self._subs = subs if subs is not None else (
            os.getenv("PARAMSPIDER_SUBS", "true").lower() in ("1", "true"))

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
        # This ParamSpider build (devanshbatham) takes only -d/-l/-s/--proxy/-p
        # and writes results/<domain>.txt; -s also streams URLs to stdout, which
        # we capture. Flags are added only if the installed build advertises them
        # (older/newer forks differ — probing keeps the wrapper portable).
        supported = self._supported_flags()
        cmd = [self._bin, "-d", domain]
        if "-s" in supported:
            cmd.append("-s")                 # stream URLs to stdout (we parse it)
        if self._subs and "--subs" in supported:
            cmd.append("--subs")             # include subdomains (only if supported)
        elif self._subs and "-s" in supported and "--subs" not in supported:
            pass  # this build folds subdomain data into the archive query already
        if "-l" in supported:
            cmd += ["-l", str(self._level)]

        result = run_command(cmd, timeout=self.timeout)
        if result.timed_out:
            raise RuntimeError(f"paramspider timed out after {self.timeout}s for {domain}")

        # Prefer the results/<domain>.txt file; fall back to captured stdout.
        params = self.parse_output(result.stdout)
        out_file = Path("results") / f"{domain}.txt"
        if out_file.is_file():
            try:
                file_params = self.parse_output(
                    out_file.read_text(encoding="utf-8", errors="ignore"))
                # Merge (file is authoritative + complete); dedup handled downstream.
                if len(file_params) > len(params):
                    params = file_params
            except OSError:
                pass
        return params

    @staticmethod
    def _supported_flags() -> set[str]:
        """Return the set of CLI flags the installed ParamSpider advertises."""
        from functools import lru_cache

        @lru_cache(maxsize=1)
        def _probe() -> frozenset[str]:
            try:
                res = run_command([resolve_tool("paramspider"), "--help"], timeout=15)
                text = (res.stdout or "") + (res.stderr or "")
            except Exception:
                return frozenset({"-d", "-s"})
            flags = set()
            for tok in ("-d", "-l", "-s", "--subs", "--proxy", "-p", "-o"):
                if tok in text:
                    flags.add(tok)
            return frozenset(flags or {"-d", "-s"})

        return set(_probe())

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
