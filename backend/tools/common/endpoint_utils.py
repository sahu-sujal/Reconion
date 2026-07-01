"""Endpoint resolution + normalization engine (Phase 6.1).

This module turns the raw strings LinkFinder / XNLinkFinder emit into fully
qualified, normalized, deduplicatable endpoints.

Two responsibilities:

  1. **Absolute URL resolution** — a raw hit like ``/api/v1/users`` or
     ``../internal/debug`` is meaningless on its own. Given the JS file it came
     from (``https://app.example.com/static/js/main.js``) we resolve it to a
     fully-qualified URL using :func:`urllib.parse.urljoin` (never string
     concatenation) so relative segments (``.`` / ``..``) collapse correctly::

         /api/v1/users        -> https://app.example.com/api/v1/users
         ../internal/debug    -> https://app.example.com/internal/debug
         ./auth/login         -> https://app.example.com/static/auth/login
         https://cdn.x/config -> https://cdn.x/config   (already absolute)

  2. **Normalization** — a canonical ``normalized_url`` used as the sole
     deduplication key. Rules mirror :mod:`tools.common.url_utils` (lowercase
     scheme/host, strip default ports, collapse duplicate slashes, drop empty
     fragments / trailing slashes) and additionally sort query parameters so
     ``?b=2&a=1`` and ``?a=1&b=2`` collapse to one endpoint.

Raw tool output is noisy: LinkFinder in particular emits template literals,
regex fragments and MIME types. :func:`resolve_endpoint` rejects anything that
cannot become a usable http(s) URL, returning ``None`` so the caller skips it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

_DEFAULT_PORTS = {"http": "80", "https": "443"}
_MULTI_SLASH_RE = re.compile(r"/{2,}")

# Raw hits we never treat as endpoints — LinkFinder/XNLinkFinder noise.
_NOISE_PREFIXES = (
    "data:", "javascript:", "mailto:", "tel:", "blob:", "about:",
    "chrome-extension:", "moz-extension:", "#",
)
# A hit must look like a path/URL — contain a slash or a dot, and only URL-safe
# characters. Template placeholders (``${…}``, ``{{…}}``) and whitespace are out.
_PLACEHOLDER_RE = re.compile(r"[\s<>\"'`\\{}$^|]")
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")
# Common non-endpoint file assets tools sometimes surface — dropped to keep the
# inventory focused on real endpoints (kept conservative on purpose).
_STATIC_ASSET_RE = re.compile(
    r"\.(?:png|jpe?g|gif|svg|ico|webp|bmp|woff2?|ttf|eot|otf|css|map)(?:\?|#|$)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class ResolvedEndpoint:
    """A fully-qualified, normalized endpoint ready for DB insertion."""

    absolute_url: str
    normalized_url: str
    scheme: str
    host: str
    path: str
    query: str
    fragment: str


def _strip_default_port(scheme: str, netloc: str) -> str:
    if ":" not in netloc:
        return netloc
    host_part, _, port = netloc.rpartition(":")
    if not port.isdigit():
        return netloc  # IPv6 literal without a port, e.g. "[::1]"
    if _DEFAULT_PORTS.get(scheme) == port:
        return host_part
    return netloc


def _sort_query(query: str) -> str:
    """Sort query parameters for order-independent deduplication.

    ``b=2&a=1`` -> ``a=1&b=2``. Preserves repeated keys and empty values; does
    not URL-decode (keeps normalization lossless and cheap).
    """
    if not query:
        return ""
    params = [p for p in query.split("&") if p]
    params.sort()
    return "&".join(params)


def _looks_processable(raw: str) -> bool:
    """Cheap pre-filter: reject obvious non-endpoints before resolution."""
    if not raw:
        return False
    low = raw.lower()
    if low.startswith(_NOISE_PREFIXES):
        return False
    if _PLACEHOLDER_RE.search(raw):
        return False
    # Must contain a path separator or a dot (so bare words like "use strict"
    # or "function" are dropped) — but allow absolute URLs regardless.
    if not _SCHEME_RE.match(raw) and "/" not in raw and "." not in raw:
        return False
    return True


def normalize_absolute(absolute_url: str) -> ResolvedEndpoint | None:
    """Normalize an already-absolute http(s) URL into a :class:`ResolvedEndpoint`.

    Returns ``None`` if the URL has no http(s) scheme or no host.
    """
    try:
        parts = urlsplit(absolute_url)
    except ValueError:
        return None

    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.netloc:
        return None

    netloc = _strip_default_port(scheme, parts.netloc.lower())

    path = _MULTI_SLASH_RE.sub("/", parts.path)
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    elif path == "/":
        path = ""

    query = _sort_query(parts.query)
    fragment = ""  # empty fragments dropped; we always drop the fragment

    normalized = urlunsplit((scheme, netloc, path, query, fragment))
    # host component of the normalized netloc (drop any userinfo for the column)
    host = netloc.rsplit("@", 1)[-1]

    return ResolvedEndpoint(
        absolute_url=absolute_url,
        normalized_url=normalized,
        scheme=scheme,
        host=host,
        path=path,
        query=query,
        fragment="",
    )


def resolve_endpoint(raw: str, base_js_url: str) -> ResolvedEndpoint | None:
    """Resolve a raw extractor hit against its originating JS file URL.

    *base_js_url* is the URL of the JavaScript file the hit was extracted from.
    Returns a fully-qualified, normalized :class:`ResolvedEndpoint`, or ``None``
    if *raw* is not a usable endpoint (noise, placeholder, static asset, or a
    value that cannot resolve to an http(s) URL).
    """
    if raw is None:
        return None
    value = raw.strip()
    if not _looks_processable(value):
        return None
    if _STATIC_ASSET_RE.search(value):
        return None

    # Protocol-relative URLs (//cdn.example.com/x) inherit the base scheme.
    if value.startswith("//"):
        base_scheme = urlsplit(base_js_url).scheme.lower() or "https"
        value = f"{base_scheme}:{value}"

    # urljoin does correct RFC-3986 relative resolution (handles ./ ../ etc.).
    # For already-absolute values it returns them unchanged.
    try:
        absolute = urljoin(base_js_url, value)
    except ValueError:
        return None

    return normalize_absolute(absolute)
