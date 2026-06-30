"""dnsx tool wrapper — DNS resolution and record enumeration.

Uses dnsx JSON output mode (-json) to capture A, AAAA, CNAME, MX, TXT, NS
records in a single pass.  Accepts a list of subdomains and resolves them all.

dnsx docs: https://github.com/projectdiscovery/dnsx
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.common.command_runner import run_command
from tools.common.tool_base import ToolBase


@dataclass
class DnsxRecord:
    """One resolved host from dnsx JSON output."""
    host: str
    a: list[str] = field(default_factory=list)
    aaaa: list[str] = field(default_factory=list)
    cname: list[str] = field(default_factory=list)
    mx: list[str] = field(default_factory=list)
    txt: list[str] = field(default_factory=list)
    ns: list[str] = field(default_factory=list)
    ttl: int | None = None

    @property
    def primary_ip(self) -> str | None:
        return self.a[0] if self.a else None


class DnsxRunner(ToolBase):
    """Resolve a list of subdomains via dnsx and return structured records.

    Unlike subdomain tools, ``run()`` accepts either a single domain string
    (treated as the wordlist target) or a list of hostnames to resolve.
    ``parse_output()`` and ``validate()`` follow the required interface.
    """

    def __init__(self, timeout: int = 600, resolvers: list[str] | None = None) -> None:
        super().__init__(timeout=timeout)
        self._resolvers = resolvers or []

    @property
    def tool_name(self) -> str:
        return "dnsx"

    # ------------------------------------------------------------------
    # Required interface
    # ------------------------------------------------------------------

    def run(self, target: str | list[str]) -> list[str]:
        """Resolve hosts and return a deduplicated sorted list of resolved FQDNs."""
        records = self.resolve(target)
        return sorted({r.host for r in records})

    def parse_output(self, raw: str) -> list[DnsxRecord]:
        """Parse newline-delimited dnsx JSON output into DnsxRecord objects."""
        records: list[DnsxRecord] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(self._parse_json_line(json.loads(line)))
            except (json.JSONDecodeError, KeyError):
                continue
        return records

    def validate(self) -> bool:
        """Return True when dnsx resolves a known host successfully."""
        try:
            result = run_command(["dnsx", "-version"], timeout=10)
            return result.returncode == 0 or b"dnsx" in result.stderr.encode()
        except RuntimeError:
            return False

    def health_check(self) -> dict[str, Any]:
        """Return a health status dict with version info."""
        try:
            result = run_command(["dnsx", "-version"], timeout=10)
            return {
                "tool": self.tool_name,
                "available": result.returncode == 0,
                "version": (result.stderr or result.stdout).strip().splitlines()[0]
                if (result.stderr or result.stdout)
                else "unknown",
            }
        except RuntimeError as exc:
            return {"tool": self.tool_name, "available": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Primary resolution method
    # ------------------------------------------------------------------

    def resolve(self, target: str | list[str]) -> list[DnsxRecord]:
        """Resolve *target* (single host or list of hosts) and return DnsxRecord list."""
        hosts: list[str] = [target] if isinstance(target, str) else list(target)
        if not hosts:
            return []

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", prefix="dnsx_input_", delete=False, encoding="utf-8"
        ) as tmp_in:
            tmp_in.write("\n".join(hosts))
            input_path = Path(tmp_in.name)

        try:
            cmd = [
                "dnsx",
                "-l", str(input_path),
                "-a", "-aaaa", "-cname", "-mx", "-txt", "-ns",
                "-resp",
                "-json",
                "-silent",
                "-retry", "2",
                "-t", "100",      # 100 concurrent threads — safe on a single machine
            ]
            if self._resolvers:
                cmd += ["-r", ",".join(self._resolvers)]

            result = run_command(cmd, timeout=self.timeout)
            if result.timed_out:
                raise RuntimeError(f"dnsx timed out after {self.timeout}s")
            return self.parse_output(result.stdout)
        finally:
            input_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json_line(obj: dict) -> DnsxRecord:
        host = obj.get("host", "")
        a = obj.get("a", [])
        aaaa = obj.get("aaaa", [])
        cname = obj.get("cname", [])
        mx_raw = obj.get("mx", [])
        txt = obj.get("txt", [])
        ns = obj.get("ns", [])

        # dnsx returns MX as "10 mx.example.com" — strip priority prefix
        mx = [v.split()[-1] if " " in v else v for v in mx_raw]

        ttl: int | None = None
        if a or aaaa:
            # TTL lives inside resp array: [{"value":"1.2.3.4","ttl":300}]
            resp = obj.get("resp", [])
            if resp and isinstance(resp, list) and isinstance(resp[0], dict):
                ttl = resp[0].get("ttl")

        return DnsxRecord(
            host=host,
            a=a if isinstance(a, list) else [a],
            aaaa=aaaa if isinstance(aaaa, list) else [aaaa],
            cname=cname if isinstance(cname, list) else [cname],
            mx=mx,
            txt=txt if isinstance(txt, list) else [txt],
            ns=ns if isinstance(ns, list) else [ns],
            ttl=ttl,
        )
