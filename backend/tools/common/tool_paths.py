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
import sys
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

# pip-installed console scripts (e.g. dnsgen) live in the active interpreter's
# bin dir. When the worker is launched by a process manager that doesn't
# "activate" the venv, this dir is absent from PATH even though the tool is
# installed, so bare-name invocations fail with "not found". Add it explicitly.
_VENV_BIN = Path(sys.executable).resolve().parent


def ensure_tools_on_path() -> None:
    """Prepend ``tools/bin`` (highest priority), then ``~/go/bin`` and the
    active interpreter's ``bin`` (for pip console scripts) to ``PATH``.

    Idempotent: an entry already present in ``PATH`` is not added again. Safe to
    call from any wrapper's import; ``command_runner`` calls it once so bare-name
    tool invocations (``["subfinder", ...]``) resolve to the bundled copy first.
    """
    current = os.environ.get("PATH", "").split(os.pathsep)
    # Add lowest-priority first so the last prepend (tools/bin) ends up first.
    for entry in (str(_VENV_BIN), str(_GO_BIN), str(TOOLS_BIN)):
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

    Falls back to a **case-insensitive** lookup for each path segment. These
    tools are cloned from GitHub, and the directory casing varies by how the
    clone was made (``tools/SecretFinder`` vs ``tools/secretfinder``). On
    case-sensitive Linux an exact-match-only lookup silently returns ``None``,
    the tool is reported unavailable, and its whole scan step is skipped with no
    output — which is exactly how a mis-cased clone hides itself.
    """
    candidate = TOOLS_DIR.joinpath(*parts)
    if candidate.is_file():
        return str(candidate)

    # Case-insensitive resolution, one segment at a time.
    current = TOOLS_DIR
    for part in parts:
        if not current.is_dir():
            return None
        target = part.lower()
        match = next(
            (entry for entry in current.iterdir() if entry.name.lower() == target),
            None,
        )
        if match is None:
            return None
        current = match
    return str(current) if current.is_file() else None


# Real (non-snap) Chrome/Chromium builds, most-preferred first. Snap paths are
# deliberately excluded — see resolve_chrome().
_CHROME_CANDIDATES = (
    "/opt/google/chrome/chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/lib/chromium/chromium",
    "/usr/lib/chromium-browser/chromium-browser",
)


def resolve_chrome() -> str | None:
    """Locate a real Chrome/Chromium binary for headless browser tools.

    Returns ``None`` if nothing suitable is found, letting the caller fall back
    to the tool's own auto-discovery.

    Why this exists: gowitness (and other chromedp-based tools) auto-discover a
    browser by probing well-known locations, and that probe consults ``snapctl``
    for the snap-packaged ``chromium``. Under a systemd unit the process cgroup
    is ``/system.slice/<unit>.service``, not a snap cgroup, so ``snapctl`` aborts
    with "is not a snap cgroup for tag snap.chromium.chromium" and the whole
    scan fails before a single page is loaded. The same command run from an
    interactive shell succeeds, which makes this look intermittent.

    Passing an explicit ``--chrome-path`` skips that discovery entirely, so we
    resolve a non-snap binary ourselves. ``CHROME_PATH`` overrides everything for
    hosts that keep the browser somewhere unusual.
    """
    override = os.getenv("CHROME_PATH")
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file():
            return str(candidate)

    for path in _CHROME_CANDIDATES:
        if Path(path).is_file():
            return path

    # PATH lookup last: a "chromium" here may be a snap wrapper (a shim under
    # /snap/bin), which is exactly what breaks under systemd, so skip those.
    for name in ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found and "/snap/" not in str(Path(found).resolve()):
            return found
    return None


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
