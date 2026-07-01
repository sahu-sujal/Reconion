"""Single source of truth for locating repo-bundled recon tools.

Every recon tool lives under ``<repo>/tools/`` — self-contained binaries in
``tools/bin/`` and Python tools (LinkFinder, xnLinkFinder) as script directories.
Rather than each wrapper recomputing the repo root with a brittle
``Path(__file__).resolve().parents[N]`` (which silently breaks if a file moves to
a different nesting depth), they all import the helpers here.

Repo-root discovery walks **up** from this file looking for a marker (``.git`` or
a ``tools`` directory), so it is independent of how deep any individual wrapper
sits. It can be overridden with the ``RECON_REPO_ROOT`` environment variable for
unusual deployments (e.g. tools installed outside the source tree).

Public API::

    TOOLS_DIR                       # <repo>/tools
    TOOLS_BIN                       # <repo>/tools/bin
    ensure_tools_on_path()          # prepend tools/bin (+ ~/go/bin) to PATH once
    bundled_binary("subfinder")     # -> "<repo>/tools/bin/subfinder" or None
    bundled_script("LinkFinder", "linkfinder.py")  # -> path str or None
    resolve_tool("httpx", fallbacks=[...])         # bundled first, then fallbacks
"""
from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path

_MARKERS = (".git", "tools")


@lru_cache(maxsize=1)
def repo_root() -> Path:
    """Locate the repository root robustly (cached).

    Order:
      1. ``RECON_REPO_ROOT`` env var, if set and it exists.
      2. Walk up from this file until a directory contains a ``tools`` dir
         (and, ideally, ``.git``). This is depth-independent.
      3. Fall back to four levels up (the historical ``parents[3]`` layout:
         ``<repo>/backend/tools/common/tool_paths.py``).
    """
    override = os.getenv("RECON_REPO_ROOT")
    if override:
        p = Path(override).expanduser().resolve()
        if p.is_dir():
            return p

    here = Path(__file__).resolve()
    for parent in here.parents:
        # A directory that holds a "tools" subdir is our repo root. Prefer one
        # that also has ".git", but accept a bare "tools" marker for exported
        # (non-git) checkouts.
        if (parent / "tools").is_dir() and (
            (parent / ".git").exists() or (parent / "tools" / "bin").is_dir()
        ):
            return parent

    # Historical fallback: <repo>/backend/tools/common/tool_paths.py → parents[3]
    return here.parents[3]


def _tools_dir() -> Path:
    return repo_root() / "tools"


TOOLS_DIR: Path = _tools_dir()
TOOLS_BIN: Path = TOOLS_DIR / "bin"

# Go-installed tools live here on this host; kept as a secondary PATH source for
# anything not bundled under tools/bin.
_GO_BIN = Path.home() / "go" / "bin"


def ensure_tools_on_path() -> None:
    """Prepend ``tools/bin`` (highest priority) then ``~/go/bin`` to ``PATH``.

    Idempotent: an entry already present in ``PATH`` is not added again. Safe to
    call from any wrapper's import; ``command_runner`` calls it once so bare-name
    tool invocations (``["subfinder", ...]``) resolve to the bundled copy first.
    """
    current = os.environ.get("PATH", "").split(os.pathsep)
    # Add lowest-priority first so the last prepend (tools/bin) ends up first.
    for entry in (str(_GO_BIN), str(TOOLS_BIN)):
        if entry and entry not in current:
            os.environ["PATH"] = entry + os.pathsep + os.environ.get("PATH", "")
            current = os.environ["PATH"].split(os.pathsep)


def bundled_binary(name: str) -> str | None:
    """Return the path to ``tools/bin/<name>`` if it exists, else ``None``."""
    candidate = TOOLS_BIN / name
    return str(candidate) if candidate.is_file() else None


def bundled_script(*parts: str) -> str | None:
    """Return the path to a bundled script under ``tools/`` if it exists.

    e.g. ``bundled_script("LinkFinder", "linkfinder.py")`` ->
    ``<repo>/tools/LinkFinder/linkfinder.py`` or ``None``.
    """
    candidate = TOOLS_DIR.joinpath(*parts)
    return str(candidate) if candidate.is_file() else None


def resolve_tool(name: str, fallbacks: tuple[str, ...] = ()) -> str:
    """Resolve an executable: bundled ``tools/bin`` first, then *fallbacks*,
    then a ``PATH`` lookup, finally the bare name (so the caller's own
    "not found" error path still fires).
    """
    found = bundled_binary(name)
    if found:
        return found
    for fb in fallbacks:
        if fb and Path(fb).is_file():
            return fb
    return shutil.which(name) or name


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

# The external tools the platform expects to find (binaries under tools/bin).
EXPECTED_BINARIES = (
    "subfinder", "assetfinder", "chaos", "findomain", "dnsgen",
    "dnsx", "httpx", "gau", "waybackurls", "katana", "hakrawler",
    "knockpy", "jsluice", "subjs",
)


def tool_availability() -> dict[str, str | None]:
    """Return ``{tool_name: resolved_path_or_None}`` for every expected binary.

    A ``None`` value means the tool is neither bundled nor on ``PATH`` — the
    scan will still run but that tool's step is recorded as failed and skipped.
    """
    ensure_tools_on_path()
    result: dict[str, str | None] = {}
    for name in EXPECTED_BINARIES:
        result[name] = bundled_binary(name) or shutil.which(name)
    return result
