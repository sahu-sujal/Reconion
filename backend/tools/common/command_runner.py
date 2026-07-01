from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from tools.common.tool_paths import ensure_tools_on_path

# Prepend the repo-bundled tools/bin (then ~/go/bin) so every recon binary
# (subfinder, dnsx, httpx, gau, katana, jsluice, …) resolves from the checked-in
# copy first, regardless of how the Celery worker or uvicorn process was
# launched. Centralised in tool_paths so every wrapper shares one source of
# truth for tool locations.
ensure_tools_on_path()


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False


def run_command(
    command: list[str],
    timeout: int,
    stdin_data: str | None = None,
) -> CommandResult:
    """Execute *command* and return a structured result.

    Never raises for timeouts or non-zero exit codes — callers inspect
    :attr:`CommandResult.timed_out` and :attr:`CommandResult.returncode`.

    Raises:
        RuntimeError: When the executable is not found on PATH.
    """
    try:
        proc = subprocess.run(
            command,
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(
            stdout=proc.stdout,
            stderr=proc.stderr,
            returncode=proc.returncode,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(stdout="", stderr="", returncode=-1, timed_out=True)
    except FileNotFoundError:
        raise RuntimeError(
            f"{command[0]!r} not found — is it installed and on PATH?"
        )


def run_command_to_file(
    command: list[str],
    timeout: int,
    stdout_path: Path,
    stdin_data: str | None = None,
) -> CommandResult:
    """Execute *command* while streaming stdout directly to *stdout_path*."""
    try:
        with stdout_path.open("w", encoding="utf-8") as stdout_file:
            proc = subprocess.run(
                command,
                input=stdin_data,
                stdout=stdout_file,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
                check=False,
            )
        return CommandResult(
            stdout="",
            stderr=proc.stderr,
            returncode=proc.returncode,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(stdout="", stderr="", returncode=-1, timed_out=True)
    except FileNotFoundError:
        raise RuntimeError(
            f"{command[0]!r} not found — is it installed and on PATH?"
        )
