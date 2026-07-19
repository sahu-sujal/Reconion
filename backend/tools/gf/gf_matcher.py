"""GF pattern matching — security-relevance tagging for URLs and endpoints.

Applies the `gf <https://github.com/tomnomnom/gf>`_ pattern set (bundled under
``tools/gf-patterns/``) to stored URLs / endpoints and returns the categories
("gf tags") each one matches.

Why the patterns are evaluated in-process instead of shelling out to ``gf``
--------------------------------------------------------------------------
``gf`` is a *grep wrapper*: it prints a ``grep`` command line and always appends
``.`` as the search target. Patterns whose ``flags`` contain ``-r`` (e.g.
``upload-fields`` with ``-HnriE``) therefore recursively grep the **working
directory** instead of reading stdin — inside a Celery worker that means walking
the whole repo (``node_modules``, ``.venv``, …) and emitting file paths as
"matches". ``gf`` also resolves its pattern directory via ``user.Current()``
(the passwd database), which ignores ``$HOME``, so the bundled pattern set
cannot be selected per-process.

The pattern files are plain JSON regex sets, so we load them once and match with
Python's ``re``. That is safe (no filesystem access), deterministic, and one
pass over the input instead of 37 subprocesses per batch.

Pattern file schema (both forms occur in the wild)::

    {"flags": "-iE",     "patterns": ["id=", "select=", ...]}   # list
    {"flags": "-HnriE",  "pattern":  "<input[^>]+type=file"}    # single regex

``flags`` is a grep flag string; only case sensitivity is meaningful here
(``-i``). The remaining flags control grep output/recursion and have no meaning
when matching a single string.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


#: Patterns written to match HTTP **response bodies** or source code rather than
#: URLs. Running them over a URL yields noise — ``urls`` matches every absolute
#: URL (100% of the inventory), ``strings`` matches any quoted text, and
#: ``go-functions`` / ``jsvar`` / ``php-errors`` / ``debug-pages`` / ``servers`` /
#: ``meg-headers`` describe response content. They stay in the bundled set (a
#: later response-body scanning phase can use them) but are excluded from URL
#: tagging so the analyst view stays meaningful.
BODY_ONLY_CATEGORIES: frozenset[str] = frozenset({
    "urls",
    "strings",
    "servers",
    "meg-headers",
    "go-functions",
    "jsvar",
    "php-errors",
    "debug-pages",
    "php-curl",
    "php-sinks",
    "php-sources",
    "php-serialized",
    "json-sec",
    "http-auth",
    "cors",
    "fw",
    "sec",
    "takeovers",
    "interestingsubs",
})


@dataclass(frozen=True)
class GfPattern:
    """One compiled gf category."""
    name: str
    regex: re.Pattern[str]
    pattern_count: int
    body_only: bool = False


def patterns_dir() -> Path:
    """Location of the bundled gf pattern JSON files."""
    from tools.common.tool_paths import TOOLS_DIR
    return TOOLS_DIR / "gf-patterns"


def _compile_pattern_file(path: Path) -> GfPattern | None:
    """Load and compile one gf pattern JSON file. Returns None if unusable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("gf pattern %s unreadable: %s", path.name, exc)
        return None

    raw = data.get("patterns")
    if raw is None:
        single = data.get("pattern")
        raw = [single] if single else []
    if isinstance(raw, str):
        raw = [raw]
    parts = [p for p in raw if isinstance(p, str) and p]
    if not parts:
        return None

    flags_str = data.get("flags") or ""
    re_flags = re.IGNORECASE if "i" in flags_str.replace("-", "") else 0

    # Compile each alternative separately so one malformed regex cannot
    # invalidate an entire category, then union the survivors.
    compiled_parts: list[str] = []
    for part in parts:
        try:
            re.compile(part)
        except re.error as exc:
            logger.warning("gf pattern %s: skipping bad regex %r (%s)", path.name, part, exc)
            continue
        compiled_parts.append(part)
    if not compiled_parts:
        return None

    union = "|".join(f"(?:{p})" for p in compiled_parts)
    try:
        regex = re.compile(union, re_flags)
    except re.error as exc:
        logger.warning("gf pattern %s failed to compile: %s", path.name, exc)
        return None

    return GfPattern(
        name=path.stem,
        regex=regex,
        pattern_count=len(compiled_parts),
        body_only=path.stem in BODY_ONLY_CATEGORIES,
    )


@lru_cache(maxsize=1)
def load_patterns() -> tuple[GfPattern, ...]:
    """Load and compile every bundled gf pattern (cached process-wide)."""
    directory = patterns_dir()
    if not directory.is_dir():
        logger.warning("gf pattern directory missing: %s", directory)
        return ()
    compiled = [
        pat for pat in (
            _compile_pattern_file(p) for p in sorted(directory.glob("*.json"))
        ) if pat is not None
    ]
    logger.info("Loaded %d gf patterns from %s", len(compiled), directory)
    return tuple(compiled)


def url_patterns() -> tuple[GfPattern, ...]:
    """Patterns meaningful for tagging a URL (excludes body-only ones)."""
    return tuple(p for p in load_patterns() if not p.body_only)


def available_categories(include_body_only: bool = False) -> list[str]:
    """Sorted gf category names that compiled successfully.

    By default only URL-taggable categories are returned — the same set the
    scan phase can actually produce.
    """
    pats = load_patterns() if include_body_only else url_patterns()
    return sorted(p.name for p in pats)


def match(value: str) -> list[str]:
    """Return the sorted gf categories *value* matches (may be empty)."""
    if not value:
        return []
    return sorted(p.name for p in url_patterns() if p.regex.search(value))


def match_many(values: list[str]) -> dict[str, list[str]]:
    """Match many values at once → ``{value: [categories]}``.

    Only values with at least one match are included, so callers can persist
    tags without filtering empties themselves.
    """
    patterns = url_patterns()
    result: dict[str, list[str]] = {}
    for value in values:
        if not value:
            continue
        tags = sorted(p.name for p in patterns if p.regex.search(value))
        if tags:
            result[value] = tags
    return result
