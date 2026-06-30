"""httpx tool wrapper — HTTP probing and technology detection.

Uses httpx JSON output mode (-json) for structured per-host results.
Accepts a list of resolved hosts and probes both http:// and https://.

httpx docs: https://github.com/projectdiscovery/httpx
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.common.command_runner import run_command
from tools.common.tool_base import ToolBase


@dataclass
class HttpxRecord:
    """One live host from httpx JSON output."""
    url: str
    host: str
    scheme: str
    port: int | None
    ip: str | None
    status_code: int | None
    title: str | None
    content_length: int | None
    server: str | None
    technologies: list[str]
    response_time: float | None      # milliseconds
    cdn: bool
    cdn_name: str | None
    waf: bool


class HttpxRunner(ToolBase):
    """Probe a list of hosts with httpx and return structured HTTP results."""

    def __init__(
        self,
        timeout: int = 600,
        threads: int = 100,
        follow_redirects: bool = True,
    ) -> None:
        super().__init__(timeout=timeout)
        self._threads = threads
        self._follow_redirects = follow_redirects

    @property
    def tool_name(self) -> str:
        return "httpx"

    # ------------------------------------------------------------------
    # Required interface
    # ------------------------------------------------------------------

    def run(self, target: str | list[str]) -> list[str]:
        """Probe hosts and return sorted list of live URLs."""
        records = self.probe(target)
        return sorted({r.url for r in records})

    def parse_output(self, raw: str) -> list[HttpxRecord]:
        """Parse newline-delimited httpx JSON output into HttpxRecord objects."""
        records: list[HttpxRecord] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(self._parse_json_line(json.loads(line)))
            except (json.JSONDecodeError, KeyError):
                continue
        return records

    # /usr/bin/httpx is the Python encode/httpx client — not projectdiscovery.
    # Prefer the Go binary at ~/go/bin/httpx.
    _BINARY_CANDIDATES = [
        "/home/sujal-sahu/go/bin/httpx",
        "/root/go/bin/httpx",
        "/usr/local/bin/httpx",
    ]

    @classmethod
    def _resolve_binary(cls) -> str:
        import shutil
        for path in cls._BINARY_CANDIDATES:
            if Path(path).is_file():
                return path
        # Fall back to PATH lookup only if a candidate isn't found
        found = shutil.which("httpx")
        return found or "httpx"

    def validate(self) -> bool:
        """Return True when projectdiscovery httpx binary is present and executable."""
        try:
            result = run_command([self._resolve_binary(), "-version"], timeout=10)
            return result.returncode == 0 or "httpx" in (result.stderr + result.stdout).lower()
        except RuntimeError:
            return False

    def health_check(self) -> dict[str, Any]:
        """Return a health status dict with version info."""
        try:
            binary = self._resolve_binary()
            result = run_command([binary, "-version"], timeout=10)
            return {
                "tool": self.tool_name,
                "available": result.returncode == 0,
                "binary": binary,
                "version": (result.stderr or result.stdout).strip().splitlines()[0]
                if (result.stderr or result.stdout)
                else "unknown",
            }
        except RuntimeError as exc:
            return {"tool": self.tool_name, "available": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Primary probe method
    # ------------------------------------------------------------------

    def probe(self, target: str | list[str]) -> list[HttpxRecord]:
        """HTTP probe *target* (single host or list) and return HttpxRecord list."""
        hosts: list[str] = [target] if isinstance(target, str) else list(target)
        if not hosts:
            return []

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", prefix="httpx_input_", delete=False, encoding="utf-8"
        ) as tmp_in:
            tmp_in.write("\n".join(hosts))
            input_path = Path(tmp_in.name)

        try:
            cmd = [
                self._resolve_binary(),
                "-l", str(input_path),
                "-json",
                "-silent",
                "-title",
                "-status-code",
                "-content-length",
                "-ip",
                "-server",
                "-tech-detect",
                "-cdn",
                "-response-time",
                "-threads", str(self._threads),
                "-timeout", "10",
                "-retries", "1",
            ]
            if self._follow_redirects:
                cmd.append("-follow-redirects")

            result = run_command(cmd, timeout=self.timeout)
            if result.timed_out:
                raise RuntimeError(f"httpx timed out after {self.timeout}s")
            return self.parse_output(result.stdout)
        finally:
            input_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json_line(obj: dict) -> HttpxRecord:
        url: str = obj.get("url", "")
        host: str = obj.get("input", url).split("://")[-1].split(":")[0].split("/")[0]
        scheme: str = obj.get("scheme", "https")

        # Port — from URL or explicit field
        port_raw = obj.get("port")
        if port_raw is None:
            try:
                url_part = url.split("://", 1)[-1]
                if ":" in url_part.split("/")[0]:
                    port_raw = int(url_part.split("/")[0].split(":")[1])
            except (ValueError, IndexError):
                pass
        port: int | None = int(port_raw) if port_raw else None

        # IP
        ip_raw = obj.get("host") or obj.get("ip")
        ip: str | None = ip_raw if isinstance(ip_raw, str) else None

        # Status
        status_code: int | None = obj.get("status_code")

        # Title — httpx returns {"title": "..."}
        title: str | None = obj.get("title")

        # Content length
        cl_raw = obj.get("content_length")
        content_length: int | None = int(cl_raw) if cl_raw is not None else None

        # Server header
        server: str | None = obj.get("webserver") or obj.get("server")

        # Technologies — httpx returns list of strings under "tech"
        tech_raw = obj.get("tech", [])
        technologies: list[str] = tech_raw if isinstance(tech_raw, list) else []

        # Response time — httpx returns "123.456ms" strings
        rt_raw = obj.get("response_time", "")
        response_time: float | None = None
        if rt_raw:
            try:
                rt_str = str(rt_raw).replace("ms", "").replace("µs", "").strip()
                response_time = float(rt_str)
                if "µs" in str(rt_raw):
                    response_time /= 1000.0
            except ValueError:
                pass

        # CDN detection
        cdn_info = obj.get("cdn", {})
        if isinstance(cdn_info, dict):
            cdn = bool(cdn_info.get("cdn_name") or cdn_info.get("cdn"))
            cdn_name: str | None = cdn_info.get("cdn_name")
        else:
            cdn = bool(cdn_info)
            cdn_name = None

        waf = bool(obj.get("waf"))

        return HttpxRecord(
            url=url,
            host=host,
            scheme=scheme,
            port=port,
            ip=ip,
            status_code=status_code,
            title=title,
            content_length=content_length,
            server=server,
            technologies=technologies,
            response_time=response_time,
            cdn=cdn,
            cdn_name=cdn_name,
            waf=waf,
        )
