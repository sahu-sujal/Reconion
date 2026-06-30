from __future__ import annotations

from pathlib import Path


def deduplicate(values: list[str]) -> list[str]:
    """Return a sorted list of unique, non-empty, stripped values."""
    return sorted({v.strip() for v in values if v.strip()})


def deduplicate_file(path: Path) -> list[str]:
    """Return sorted unique non-empty lines from a file without reading it twice."""
    values: set[str] = set()
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            value = line.strip()
            if value:
                values.add(value)
    return sorted(values)


def merge_sources(existing: str | None, new_source: str) -> str:
    """Merge source strings, returning comma-separated sorted unique sources.

    Examples::
        merge_sources(None, "subfinder")           -> "subfinder"
        merge_sources("subfinder", "assetfinder")  -> "assetfinder,subfinder"
        merge_sources("subfinder", "subfinder")    -> "subfinder"
    """
    parts: set[str] = set()
    if existing:
        parts.update(s.strip() for s in existing.split(",") if s.strip())
    parts.update(s.strip() for s in new_source.split(",") if s.strip())
    return ",".join(sorted(parts))


def build_source_map(
    *tool_results: tuple[str, list[str]],
) -> dict[str, str]:
    """Build a value → sources mapping from multiple tool result sets.

    Args:
        tool_results: Pairs of ``(tool_name, list_of_values)``.

    Returns:
        Dict mapping each discovered value to its comma-separated sorted
        source string, e.g. ``{"api.example.com": "assetfinder,subfinder"}``.

    Example::
        build_source_map(
            ("subfinder",   ["a.x.com", "b.x.com"]),
            ("assetfinder", ["a.x.com", "c.x.com"]),
        )
        # -> {"a.x.com": "assetfinder,subfinder",
        #     "b.x.com": "subfinder",
        #     "c.x.com": "assetfinder"}
    """
    accumulated: dict[str, set[str]] = {}
    for tool_name, values in tool_results:
        for value in values:
            accumulated.setdefault(value, set()).add(tool_name)
    return {
        value: ",".join(sorted(sources))
        for value, sources in accumulated.items()
    }
