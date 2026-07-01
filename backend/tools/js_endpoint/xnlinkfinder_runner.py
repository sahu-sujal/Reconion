"""XNLinkFinder wrapper — JavaScript endpoint extraction (Phase 6.1).

XNLinkFinder (https://github.com/xnl-h4ck3r/xnLinkFinder) is an evolution of
LinkFinder that scans local files, directories and archives for links. We run it
in **offline directory mode** — it ingests a directory of already-downloaded JS
files in a single pass (``os.path.isdir(input)`` triggers ``dirPassed`` inside
the tool) and writes discovered links to an output file:

    xnLinkFinder -i <dir> -o <out.txt> -sf <scope-domain> -nb

  * directory input     the tool parses file *contents* (a single-file input is
                        instead treated as a URL to fetch — which we never want).
  * ``-sf <domain>``    scope filter — mandatory in recent versions; must be a
                        real domain (``*`` is rejected). We pass the scope's
                        registrable root; the worker re-filters at persistence.
  * ``-nb``             suppress the banner so the output file stays clean.

Robustness:
  * We invoke the tool through the current interpreter as ``python -m
    xnLinkFinder.xnLinkFinder`` when the package is importable, so a broken
    console-script shebang never matters; otherwise we fall back to the binary.
  * ``validate()`` runs a cached *functional* probe (parse a tiny known JS file)
    rather than just checking the binary exists — so a broken install (e.g. a
    missing ``termcolor`` dependency, or a Python-version incompatibility) is
    reported as unavailable and the worker skips it instead of burning time on
    every batch.

Returns *raw* endpoint strings; resolution/normalization is the worker's job.
"""
from __future__ import annotations

import os
import pty
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tools.common.tool_paths import bundled_script
from tools.js_endpoint.endpoint_tool_base import EndpointToolBase


def _repo_script() -> str | None:
    """Path to the repo-bundled xnLinkFinder script, if present."""
    import os

    override = os.getenv("XNLINKFINDER_SCRIPT", "")
    if override and Path(override).is_file():
        return override
    return bundled_script("xnLinkFinder", "xnLinkFinder", "xnLinkFinder.py")


def _module_importable() -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec("xnLinkFinder.xnLinkFinder") is not None
    except (ImportError, ValueError):
        return False


def _binary_path() -> str | None:
    import os

    for candidate in (
        os.getenv("XNLINKFINDER_PATH", ""),
        shutil.which("xnLinkFinder") or "",
        str(Path.home() / ".local" / "bin" / "xnLinkFinder"),
        "/usr/local/bin/xnLinkFinder",
    ):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


class XnLinkFinderRunner(EndpointToolBase):
    """Extract endpoints from a directory of local JS files using XNLinkFinder."""

    def __init__(self, timeout: int = 300, scope_filter: str = "") -> None:
        super().__init__(timeout=timeout)
        # Resolution order: importable module → console script → repo script.
        # Module invocation ("python -m xnLinkFinder.xnLinkFinder") is preferred
        # because the tool does `__import__("xnLinkFinder").__version__` at
        # startup — running the bundled script *by path* resolves the wrong
        # module and crashes with AttributeError, whereas `-m` loads the package
        # (and its __init__ __version__) correctly.
        self._use_module = _module_importable()
        self._bin = None if self._use_module else _binary_path()
        self._script = None if (self._use_module or self._bin) else _repo_script()
        # Scope filter must be a real domain. Fall back to the scope target's
        # registrable root; "example.com" is a harmless default that still lets
        # offline parsing return in-path results (the worker re-filters anyway).
        self._scope_filter = self._normalize_scope(scope_filter)
        self._healthy: bool | None = None  # cached functional-probe result

    @property
    def tool_name(self) -> str:
        return "XNLINKFINDER"

    @staticmethod
    def _normalize_scope(scope_filter: str) -> str:
        s = (scope_filter or "").strip().lstrip("*.").rstrip("/")
        # XNLinkFinder rejects "*" and bare wildcards; require a domain-ish value.
        if not s or s == "*" or "." not in s:
            return "example.com"
        return s

    def _base_cmd(self) -> list[str]:
        if self._use_module:
            return [sys.executable, "-m", "xnLinkFinder.xnLinkFinder"]
        if self._bin:
            return [self._bin]
        assert self._script is not None
        return [sys.executable, self._script]

    def validate(self) -> None:
        if not self._script and not self._use_module and not self._bin:
            raise RuntimeError(
                "xnLinkFinder not found — bundle it under <repo>/tools/xnLinkFinder, "
                "install it (pip install xnLinkFinder), or set XNLINKFINDER_PATH"
            )
        if not self._functional_probe():
            raise RuntimeError(
                "xnLinkFinder is installed but not runnable in this environment "
                "(import error or incompatible runtime) — skipping it"
            )

    def _functional_probe(self) -> bool:
        """Run the tool once against a known JS sample; cache the outcome."""
        if self._healthy is not None:
            return self._healthy
        self._healthy = False
        try:
            with tempfile.TemporaryDirectory(prefix="xnl_probe_") as tmp:
                d = Path(tmp)
                (d / "probe.js").write_text(
                    'fetch("https://probe.example.com/api/v1/health");\n'
                    'var u = "/internal/admin";\n',
                    encoding="utf-8",
                )
                hits = self._invoke(d, timeout=30)
            self._healthy = len(hits) > 0
        except Exception:
            self._healthy = False
        return self._healthy

    def parse_output(self, raw_output: str) -> list[str]:
        """XNLinkFinder's links output is one raw link per line."""
        return self._clean_lines(raw_output)

    def _invoke(self, input_dir: Path, timeout: int) -> list[str]:
        """Run the tool over *input_dir* and return parsed raw links.

        XNLinkFinder gates ALL of its work behind ``sys.stdout.isatty()`` — run
        headless (as a Celery subprocess) it silently does nothing and writes an
        empty output file. We therefore run it attached to a pseudo-terminal so
        ``isatty()`` is True and it processes normally. Its results still go to
        the ``-o`` file, which we read afterwards (its stdout is just progress
        chatter we discard).
        """
        out_file = input_dir / "_xnlinkfinder_links.txt"
        # XNLinkFinder also writes a "potential parameters" file, defaulting to
        # parameters.txt in the CWD (which would litter the repo). Phase 6.1 is
        # endpoint discovery only, so we point it inside the disposable input dir
        # and never read it.
        params_file = input_dir / "_xnlinkfinder_params.txt"
        out_file.unlink(missing_ok=True)

        cmd = [
            *self._base_cmd(),
            "-i", str(input_dir),
            "-o", str(out_file),
            "-op", str(params_file),
            "-sf", self._scope_filter,
            "-nb",
        ]
        self._run_under_pty(cmd, timeout)

        params_file.unlink(missing_ok=True)  # discard — not used in this phase
        if not out_file.exists():
            return []
        try:
            raw = out_file.read_text(encoding="utf-8", errors="replace")
        finally:
            out_file.unlink(missing_ok=True)
        return self.parse_output(raw)

    @staticmethod
    def _run_under_pty(cmd: list[str], timeout: int) -> None:
        """Run *cmd* with a controlling pseudo-terminal, enforcing *timeout*.

        XNLinkFinder only does its work when ``sys.stdout.isatty()`` is True, so
        it must run attached to a TTY that is its *controlling* terminal.

        We do this with a plain ``subprocess.Popen`` (NOT a manual ``os.fork`` +
        ``pty.spawn``): inside a Celery prefork worker we are already a forked
        child, and a second manual fork + ``os.waitpid`` races Celery's own
        SIGCHLD reaper and intermittently deadlocks (the "unavailable" flapping).
        ``subprocess`` reaps its own child safely.

        The child's stdin/stdout/stderr are the PTY slave; ``start_new_session``
        + ``TIOCSCTTY`` (via a preexec hook) make it the controlling terminal.
        We drain the master fd in a thread so the child never blocks writing,
        and discard that output (results go to the ``-o`` file).
        """
        import fcntl
        import termios
        import threading

        master_fd, slave_fd = pty.openpty()

        def _preexec() -> None:
            # New session, then claim the pty as the controlling terminal. By
            # the time preexec runs, subprocess has already dup2'd slave_fd onto
            # fd 0/1/2, so we ioctl fd 0 (the child's own copy of the slave) —
            # ioctl on the parent's slave_fd number would target the wrong fd.
            os.setsid()
            try:
                fcntl.ioctl(0, termios.TIOCSCTTY, 0)
            except OSError:
                pass

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                preexec_fn=_preexec,
                close_fds=True,
            )
        except FileNotFoundError as exc:
            os.close(master_fd)
            os.close(slave_fd)
            raise RuntimeError(f"xnLinkFinder not runnable: {exc}")
        finally:
            os.close(slave_fd)  # child holds its own copy

        # Drain (and discard) the child's terminal output so it never blocks.
        def _drain() -> None:
            try:
                while True:
                    if not os.read(master_fd, 65536):
                        break
            except OSError:
                pass

        drainer = threading.Thread(target=_drain, daemon=True)
        drainer.start()

        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
            raise RuntimeError(f"xnLinkFinder timed out after {timeout}s")
        finally:
            try:
                os.close(master_fd)
            except OSError:
                pass
            drainer.join(timeout=1)

    def run(self, js_paths: list[Path]) -> list[str]:
        """Run XNLinkFinder over the directory containing *js_paths*."""
        self.validate()
        existing = [p for p in js_paths if p.is_file() and p.stat().st_size > 0]
        if not existing:
            return []
        return self._invoke(existing[0].parent, timeout=self.timeout)
