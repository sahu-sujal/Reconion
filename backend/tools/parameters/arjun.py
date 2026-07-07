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
import logging
import os
import tempfile
from pathlib import Path

from tools.common.command_runner import run_command
from tools.common.tool_paths import resolve_tool
from tools.parameters.parameter_tool_base import ParameterToolBase, RawParameter

_log = logging.getLogger(__name__)


class ArjunRunner(ParameterToolBase):
    """Discover accepted HTTP parameters on target URLs using Arjun."""

    def __init__(
        self,
        timeout: int = 1200,
        threads: int | None = None,
        stable: bool = False,
        rate_limit: int | None = None,
        methods: str | None = None,
        passive: bool = True,
        user_agent: str | None = None,
        wordlist: str | None = None,
        chunks: int | None = None,
    ) -> None:
        super().__init__(timeout=timeout)
        # Arjun ships as a Python console script; fall back to `arjun` on PATH.
        self._bin = resolve_tool("arjun")
        if threads is None:
            threads = int(os.getenv("ARJUN_THREADS", "10"))
        self._threads = max(1, threads)
        # `--stable` trades speed for fewer false positives; env-tunable.
        self._stable = stable or os.getenv("ARJUN_STABLE", "").lower() in ("1", "true")
        # Requests/second cap — be polite to the target (default 10).
        self._rate_limit = rate_limit if rate_limit is not None else int(
            os.getenv("ARJUN_RATE_LIMIT", "10"))
        # HTTP methods to probe with (comma-separated). GET,POST by default.
        self._methods = methods or os.getenv("ARJUN_METHODS", "GET,POST")
        # Wordlist controls how many params are tested per URL — the dominant
        # cost. Arjun's default is db/large.txt (~26k params) which, at a rate
        # limit, makes a URL take many seconds. We default to the *medium* list
        # (~11k) for a usable speed/coverage balance. Accepts "small"/"medium"/
        # "large" (mapped to Arjun's bundled db) or an explicit file path.
        self._wordlist = self._resolve_wordlist(
            wordlist or os.getenv("ARJUN_WORDLIST", "medium"))
        # Chunk size = params sent per request. Bigger chunk → fewer round-trips
        # per URL → faster. Arjun's default is auto; we raise it to cut requests.
        self._chunks = chunks if chunks is not None else int(
            os.getenv("ARJUN_CHUNKS", "500"))
        # `--passive` adds passive parameter sources (wordlists from archives,
        # commoncrawl, etc.) on top of active probing — "both" per the spec.
        self._passive = passive if passive is not None else (
            os.getenv("ARJUN_PASSIVE", "true").lower() in ("1", "true"))
        self._user_agent = user_agent or os.getenv(
            "ARJUN_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        )

    @staticmethod
    def _resolve_wordlist(spec: str | None) -> str | None:
        """Map a wordlist spec to a path. ``small|medium|large`` → Arjun's db.

        An explicit existing file path is used as-is. Returns ``None`` (Arjun's
        own default) if a named list can't be located.
        """
        if not spec:
            return None
        named = spec.strip().lower()
        if named in ("small", "medium", "large"):
            # Arjun installs its db next to the package.
            import glob
            for base in (
                "/usr/lib/python3/dist-packages/arjun/db",
                "/usr/local/lib/python3*/dist-packages/arjun/db",
                str(Path.home() / ".local/lib/python3*/site-packages/arjun/db"),
            ):
                for d in glob.glob(base):
                    candidate = Path(d) / f"{named}.txt"
                    if candidate.is_file():
                        return str(candidate)
            return None
        # Treat as an explicit path.
        return spec if Path(spec).is_file() else None

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
        """Run Arjun over *targets* (a batch of URLs).

        Arjun's ``-m`` takes a single HTTP method per invocation, so to probe
        both GET and POST (per the spec) we run once per method and merge. Each
        run writes a JSON report we parse; both temp files are cleaned up.
        """
        self.validate()
        urls = [u for u in targets if u]
        if not urls:
            return []

        methods = [m.strip().upper() for m in self._methods.split(",") if m.strip()] or ["GET"]
        results: list[RawParameter] = []
        with tempfile.TemporaryDirectory(prefix="arjun_") as tmp:
            in_path = Path(tmp) / "targets.txt"
            in_path.write_text("\n".join(urls) + "\n", encoding="utf-8")

            for method in methods:
                out_path = Path(tmp) / f"arjun_out_{method}.json"
                cmd = [
                    self._bin,
                    "-i", str(in_path),
                    "-oJ", str(out_path),          # JSON report (reliable per-URL parse)
                    "-t", str(self._threads),      # concurrency
                    "-c", str(self._chunks),       # params/request — bigger = fewer requests
                    "--rate-limit", str(self._rate_limit),  # requests/sec cap (politeness)
                    "-m", method,                  # one verb per run (GET, then POST)
                    "--headers", f"User-Agent: {self._user_agent}",
                ]
                if self._wordlist:
                    cmd += ["-w", self._wordlist]  # smaller list → far fewer requests/URL
                if self._passive:
                    cmd.append("--passive")        # passive sources + active = both
                if self._stable:
                    cmd.append("--stable")

                result = run_command(cmd, timeout=self.timeout)

                # On timeout, DON'T discard the batch — Arjun writes its JSON
                # report incrementally, so salvage whatever it finished before it
                # was killed. A slow batch still contributes its completed URLs
                # instead of returning nothing.
                if out_path.is_file():
                    try:
                        results.extend(self.parse_output(out_path.read_text(encoding="utf-8")))
                    except OSError:
                        pass
                if result.timed_out:
                    _log.warning(
                        "arjun timed out after %ss (%s) on %d URLs — kept %d partial params; "
                        "consider lowering PARAM_ASSET_BATCH_SIZE or ARJUN_WORDLIST=small",
                        self.timeout, method, len(urls), len(results),
                    )
        return results
