from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import tools.common.command_runner  # ensure ~/go/bin is on PATH
from tools.common.dedupe_utils import deduplicate
from tools.common.tool_base import ToolBase

# Resolve knockpy explicitly so the runner works regardless of how the worker
# process was launched: the repo-bundled copy under tools/bin first, then the
# system install.
from tools.common.tool_paths import resolve_tool

_KNOCKPY_BIN = resolve_tool("knockpy", fallbacks=("/usr/bin/knockpy",))


class KnockpyRunner(ToolBase):
    """Enumerate subdomains using knockpy v9 in recon + JSON mode.

    Command: knockpy -d DOMAIN --recon --json
    Output:  JSON list printed to stdout, each entry has a "domain" key.
    """

    @property
    def tool_name(self) -> str:
        return "knockpy"

    def run(  # type: ignore[override]
        self, target: str, raw_report_dir: Path | str | None = None
    ) -> list[str]:
        """Enumerate subdomains for *target*.

        If *raw_report_dir* is given, knockpy's full JSON report is written there
        as ``knockpy.json`` (e.g. ``subdomains/raw/knockpy.json``). We persist the
        stdout JSON — the authoritative data we already parse — so it is complete
        and independent of knockpy's version-specific internal save behaviour.
        """
        if not Path(_KNOCKPY_BIN).exists():
            raise RuntimeError(
                f"knockpy not found at {_KNOCKPY_BIN} — is knock-subdomains installed?"
            )
        # knockpy has no flag to control where it saves its results: depending
        # on the version it writes a "<domain>_<timestamp>.json" report and/or a
        # reports.db to a fixed location. Under systemd the worker's CWD is the
        # repo's backend/ dir, so those artifacts litter the source tree. We only
        # need the stdout JSON, so we contain knockpy's writes in a throwaway
        # temp dir and delete it. Belt-and-braces:
        #   1. cwd=work_dir  — catches versions that write to the process CWD.
        #   2. KNOCKPY_DB    — points the reports.db into the temp dir so the DB
        #      save path can never reach backend/.
        #   3. a post-run sweep — removes any stray report that still leaked into
        #      the real CWD, regardless of knockpy's internal naming.
        #
        # NOTE: we deliberately do NOT override HOME. knockpy reads its recon
        # config (and API keys) from ~/.knockpy/recon_services.json; pointing HOME
        # at an empty temp dir makes --recon find no services and return zero
        # subdomains — the exact "empty scan, but manual run works" bug. KNOCKPY_DB
        # already contains the only artifact (the DB) that HOME was meant to
        # redirect, so overriding HOME is both unnecessary and harmful.
        work_dir = tempfile.mkdtemp(prefix="knockpy_")
        env = dict(os.environ)
        env["KNOCKPY_DB"] = str(Path(work_dir) / "reports.db")
        try:
            proc = subprocess.run(
                [_KNOCKPY_BIN, "-d", target, "--recon", "--json"],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
                cwd=work_dir,
                env=env,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"knockpy timed out after {self.timeout}s")
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
            _sweep_stray_reports(target)

        if raw_report_dir is not None:
            _save_json_report(raw_report_dir, proc.stdout, proc.stderr, proc.returncode)

        stdout = (proc.stdout or "").strip()
        if not stdout:
            # Empty stdout is never a legitimate "no subdomains" result — knockpy
            # prints at least "[]". It means knockpy could not run: most often
            # ~/.knockpy/recon_services.json is missing (run `knockpy --setup`),
            # so --recon has no services to query. Raise instead of returning []
            # so the scan reports a FAILED tool with a real message rather than a
            # silent "completed, 0 found".
            detail = (proc.stderr or "").strip().splitlines()
            hint = detail[-1] if detail else "no output on stdout or stderr"
            raise RuntimeError(
                f"knockpy produced no output (exit {proc.returncode}): {hint}. "
                "If ~/.knockpy/recon_services.json is missing, run "
                "`knockpy --setup` as the user that runs the worker."
            )

        return _parse_knockpy_stdout(stdout)


def _save_json_report(
    raw_report_dir: Path | str,
    stdout: str,
    stderr: str = "",
    returncode: int | None = None,
) -> None:
    """Persist knockpy's output to ``<raw_report_dir>/``.

    Writes ``knockpy.json`` whenever there is stdout. When stdout is empty the
    run failed, so ``knockpy.error.txt`` is written with the exit code and
    stderr instead — previously nothing was written at all, which left a failed
    knockpy indistinguishable from one that was never invoked.

    Best-effort: a failure to persist must never fail the scan.
    """
    stdout = (stdout or "").strip()
    try:
        out_dir = Path(raw_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        if stdout:
            (out_dir / "knockpy.json").write_text(stdout, encoding="utf-8")
        else:
            (out_dir / "knockpy.error.txt").write_text(
                f"exit_code={returncode}\n\n--- stderr ---\n{(stderr or '').strip()}\n",
                encoding="utf-8",
            )
    except OSError:
        pass


def _sweep_stray_reports(target: str) -> None:
    """Remove any "<target>_<timestamp>.json" report knockpy left in the real
    CWD, in case a knockpy build ignores cwd/env and writes to os.getcwd().
    """
    for stray in glob.glob(f"{glob.escape(target)}_*.json"):
        try:
            os.remove(stray)
        except OSError:
            pass


def _parse_knockpy_stdout(stdout: str) -> list[str]:
    """Extract subdomain strings from knockpy --json stdout.

    knockpy v9 emits a JSON array where each element is an object with a
    "domain" key, e.g.:
        [{"domain": "api.example.com", "ip": [...], ...}, ...]
    """
    stdout = stdout.strip()
    if not stdout:
        return []

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        # stdout may have mixed progress lines before the JSON block —
        # find the first '[' and try from there
        bracket = stdout.find("[")
        if bracket == -1:
            return []
        try:
            data = json.loads(stdout[bracket:])
        except json.JSONDecodeError:
            return []

    if not isinstance(data, list):
        return []

    subdomains: list[str] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        value = entry.get("domain", "")
        if value and "." in value:
            subdomains.append(value.strip().lower())

    return deduplicate(subdomains)
