"""URL normalization, parsing and JS detection helpers (Phase 5).

The normalization rules (per spec):

    https://example.com/   ->  https://example.com
    https://example.com    ->  https://example.com

  * lowercase scheme + host
  * strip default ports (80 for http, 443 for https)
  * collapse duplicate slashes in the path
  * drop empty fragments and empty queries
  * drop a single trailing slash (but keep "/" for the bare root → "")

A :class:`ParsedUrl` exposes every component the ``urls`` table stores so the
worker can build DB rows without re-parsing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

_DEFAULT_PORTS = {"http": "80", "https": "443"}
_MULTI_SLASH_RE = re.compile(r"/{2,}")
# A conservative set of file extensions we treat as JavaScript assets.
_JS_EXTENSIONS = {"js", "mjs", "cjs", "jsx", "ts", "tsx"}
_JS_TAIL_RE = re.compile(r"\.(?:m|c)?js(?:x)?(?:\?|#|$)", re.IGNORECASE)


@dataclass(slots=True)
class ParsedUrl:
    """Fully decomposed, normalized URL ready for DB insertion."""

    raw: str
    normalized: str
    scheme: str
    host: str
    path: str
    query: str
    fragment: str
    extension: str | None
    directory: str
    filename: str | None
    depth: int
    parameter_count: int
    has_parameters: bool

    @property
    def is_js(self) -> bool:
        return self.extension in _JS_EXTENSIONS


def _strip_default_port(scheme: str, netloc: str) -> str:
    """Remove a redundant default port from *netloc* (keeps userinfo if any)."""
    if ":" not in netloc:
        return netloc
    # Don't touch IPv6 literals without a trailing port, e.g. "[::1]"
    host_part, _, port = netloc.rpartition(":")
    if not port.isdigit():
        return netloc
    if _DEFAULT_PORTS.get(scheme) == port:
        return host_part
    return netloc


def normalize_url(raw: str) -> str | None:
    """Return the canonical form of *raw*, or ``None`` if it is not usable.

    Returns ``None`` for empty input or values without an http(s) scheme and
    host (relative paths are resolved by the caller before normalization).
    """
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None

    try:
        parts = urlsplit(value)
    except ValueError:
        return None

    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return None
    if not parts.netloc:
        return None

    netloc = _strip_default_port(scheme, parts.netloc.lower())

    # Collapse duplicate slashes inside the path, then drop a single trailing
    # slash so ".../" and "..." normalize identically. The bare root path "/"
    # collapses to "" so "https://x.com/" == "https://x.com".
    path = _MULTI_SLASH_RE.sub("/", parts.path)
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    elif path == "/":
        path = ""

    # Empty query / fragment are dropped (urlunsplit omits them when empty).
    query = parts.query
    fragment = ""  # spec: remove empty fragments — we always drop the fragment

    return urlunsplit((scheme, netloc, path, query, fragment))


def _extension_of(path: str) -> str | None:
    """Return the lowercase file extension of the last path segment, if any."""
    segment = path.rsplit("/", 1)[-1]
    if "." not in segment:
        return None
    ext = segment.rsplit(".", 1)[-1].lower()
    # Guard against absurdly long "extensions" (not real file types).
    if not ext or len(ext) > 12 or not ext.isalnum():
        return None
    return ext


def parse_url(raw: str) -> ParsedUrl | None:
    """Parse *raw* into a :class:`ParsedUrl`, returning ``None`` if unusable."""
    normalized = normalize_url(raw)
    if normalized is None:
        return None

    parts = urlsplit(normalized)
    scheme = parts.scheme
    host = parts.netloc
    path = parts.path
    query = parts.query
    fragment = parts.fragment

    # depth = number of non-empty path segments
    segments = [seg for seg in path.split("/") if seg]
    depth = len(segments)

    last = segments[-1] if segments else ""
    extension = _extension_of(path)
    # filename only when the last segment looks like a file (has an extension)
    filename = last if extension else None
    if filename:
        directory = path[: path.rfind("/") + 1] or "/"
    else:
        directory = path if path.endswith("/") or not path else path + "/"
        if not directory:
            directory = "/"

    params = [p for p in query.split("&") if p] if query else []
    parameter_count = len(params)

    return ParsedUrl(
        raw=raw.strip(),
        normalized=normalized,
        scheme=scheme,
        host=host,
        path=path,
        query=query,
        fragment=fragment,
        extension=extension,
        directory=directory,
        filename=filename,
        depth=depth,
        parameter_count=parameter_count,
        has_parameters=parameter_count > 0,
    )


def is_js_url(raw: str) -> bool:
    """Cheap check whether *raw* points to a JavaScript asset."""
    return bool(_JS_TAIL_RE.search(raw or ""))
