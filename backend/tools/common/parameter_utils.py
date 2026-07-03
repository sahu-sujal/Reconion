"""Parameter normalization + type classification engine — Phase 6.4.

Pure, network-free logic shared by the Parameter Discovery worker and any tool
wrapper. It is the **single source of truth** for how a raw parameter name
discovered by Arjun / ParamSpider / (future) ParamMiner is turned into a canonical
form and labelled with a parameter *type* (Identifier, Pagination, Redirect, …).

Design
------
* ``normalize_parameter`` lower-cases and canonicalises separators so ``ID``,
  ``User_ID`` and ``redirectURL`` collapse to ``id`` / ``user_id`` / ``redirecturl``
  respectively. Normalization is configurable via :class:`NormalizationConfig`.
* ``classify_parameter`` maps a (normalized) name to a :data:`ParameterType`
  using exact-name and substring rules walked in priority order. Adding a new
  type is a one-line append to :data:`_TYPE_RULES` — no schema or worker change.

Both functions are deliberately allocation-light: parameter discovery emits
hundreds of thousands of names, so the hot path avoids regex where a set lookup
suffices.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Parameter types (stable string keys stored in the DB)                         #
# --------------------------------------------------------------------------- #

IDENTIFIER = "IDENTIFIER"
PAGINATION = "PAGINATION"
SORTING = "SORTING"
REDIRECT = "REDIRECT"
URL_TYPE = "URL"
CALLBACK = "CALLBACK"
FILE = "FILE"
FILESYSTEM = "FILESYSTEM"
COMMAND = "COMMAND"
AUTHENTICATION = "AUTHENTICATION"
CREDENTIAL = "CREDENTIAL"
IDENTITY = "IDENTITY"
SEARCH = "SEARCH"
LOCALIZATION = "LOCALIZATION"
OAUTH = "OAUTH"
UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ParameterTypeMeta:
    """Presentation metadata for one parameter type (drives the UI/legend)."""

    type: str
    label: str
    # Coarse security relevance used to colour/group the type in the Explorer.
    interesting: bool = False


# Ordered metadata — also the display order in the Parameter Explorer legend.
PARAMETER_TYPE_META: dict[str, ParameterTypeMeta] = {
    IDENTIFIER: ParameterTypeMeta(IDENTIFIER, "Identifier", interesting=True),
    REDIRECT: ParameterTypeMeta(REDIRECT, "Redirect", interesting=True),
    URL_TYPE: ParameterTypeMeta(URL_TYPE, "URL", interesting=True),
    CALLBACK: ParameterTypeMeta(CALLBACK, "Callback", interesting=True),
    FILE: ParameterTypeMeta(FILE, "File", interesting=True),
    FILESYSTEM: ParameterTypeMeta(FILESYSTEM, "Filesystem", interesting=True),
    COMMAND: ParameterTypeMeta(COMMAND, "Command", interesting=True),
    AUTHENTICATION: ParameterTypeMeta(AUTHENTICATION, "Authentication", interesting=True),
    CREDENTIAL: ParameterTypeMeta(CREDENTIAL, "Credential", interesting=True),
    OAUTH: ParameterTypeMeta(OAUTH, "OAuth", interesting=True),
    IDENTITY: ParameterTypeMeta(IDENTITY, "Identity", interesting=True),
    SEARCH: ParameterTypeMeta(SEARCH, "Search"),
    PAGINATION: ParameterTypeMeta(PAGINATION, "Pagination"),
    SORTING: ParameterTypeMeta(SORTING, "Sorting"),
    LOCALIZATION: ParameterTypeMeta(LOCALIZATION, "Localization"),
    UNKNOWN: ParameterTypeMeta(UNKNOWN, "Unknown"),
}


# --------------------------------------------------------------------------- #
# Normalization                                                                 #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class NormalizationConfig:
    """Configurable parameter-name normalization.

    Defaults match the spec (``ID`` → ``id``, ``User_ID`` → ``user_id``,
    ``redirectURL`` → ``redirecturl``): lowercase everything and collapse
    separators to a single underscore, but keep the internal word boundaries
    that came from explicit separators.
    """

    lowercase: bool = True
    # Collapse runs of these separator characters to a single underscore.
    collapse_separators: bool = True
    # Strip a leading array/bracket marker like ``amp;`` or trailing ``[]``.
    strip_array_suffix: bool = True
    max_length: int = 128


_DEFAULT_CONFIG = NormalizationConfig()

# Characters treated as separators between words in a parameter name.
_SEP_RE = re.compile(r"[\s\-.:/+]+")
# HTML-entity leakage seen in crawler output (``amp;foo`` → ``foo``).
_AMP_PREFIX_RE = re.compile(r"^(?:amp;|3d)+", re.IGNORECASE)
# Only these characters are allowed to survive in a stored parameter name.
_ALLOWED_RE = re.compile(r"[^a-z0-9_\[\]]")


def normalize_parameter(name: str, config: NormalizationConfig | None = None) -> str | None:
    """Normalize a raw parameter name to its canonical stored form.

    Returns ``None`` for empty / junk names (so callers drop them). The output
    is lowercase with runs of separators collapsed to ``_``; original casing and
    camelCase boundaries are intentionally flattened (``redirectURL`` →
    ``redirecturl``) to match the spec's dedup semantics.
    """
    cfg = config or _DEFAULT_CONFIG
    if name is None:
        return None
    raw = name.strip()
    if not raw:
        return None

    # URL-decoded artefacts sometimes prefix the name.
    raw = _AMP_PREFIX_RE.sub("", raw)

    if cfg.lowercase:
        raw = raw.lower()

    if cfg.strip_array_suffix and raw.endswith("[]"):
        raw = raw[:-2]

    if cfg.collapse_separators:
        raw = _SEP_RE.sub("_", raw)
        raw = re.sub(r"_+", "_", raw).strip("_")

    # Drop anything still not in the allowed set (control chars, quotes, %xx).
    raw = _ALLOWED_RE.sub("", raw)
    raw = raw.strip("_")
    if not raw:
        return None
    if len(raw) > cfg.max_length:
        raw = raw[: cfg.max_length]
    return raw or None


# --------------------------------------------------------------------------- #
# Type classification                                                           #
# --------------------------------------------------------------------------- #

# Exact-name matches (highest confidence). Keyed on the NORMALIZED name.
_EXACT_TYPES: dict[str, str] = {
    # Identifier
    "id": IDENTIFIER, "uid": IDENTIFIER, "uuid": IDENTIFIER, "guid": IDENTIFIER,
    "user_id": IDENTIFIER, "userid": IDENTIFIER, "account_id": IDENTIFIER,
    "object_id": IDENTIFIER, "item_id": IDENTIFIER, "pid": IDENTIFIER,
    # Pagination
    "page": PAGINATION, "limit": PAGINATION, "offset": PAGINATION,
    "per_page": PAGINATION, "perpage": PAGINATION, "size": PAGINATION,
    "count": PAGINATION, "start": PAGINATION, "cursor": PAGINATION,
    # Sorting
    "sort": SORTING, "order": SORTING, "orderby": SORTING, "order_by": SORTING,
    "sortby": SORTING, "sort_by": SORTING, "dir": SORTING, "direction": SORTING,
    # Redirect
    "redirect": REDIRECT, "redirect_url": REDIRECT, "redirecturl": REDIRECT,
    "next": REDIRECT, "return": REDIRECT, "return_url": REDIRECT,
    "returnurl": REDIRECT, "returnto": REDIRECT, "return_to": REDIRECT,
    "continue": REDIRECT, "dest": REDIRECT, "destination": REDIRECT,
    "goto": REDIRECT, "forward": REDIRECT,
    # URL
    "url": URL_TYPE, "uri": URL_TYPE, "link": URL_TYPE, "site": URL_TYPE,
    "domain": URL_TYPE, "host": URL_TYPE, "target": URL_TYPE, "src": URL_TYPE,
    "href": URL_TYPE, "image_url": URL_TYPE, "img": URL_TYPE, "feed": URL_TYPE,
    # Callback
    "callback": CALLBACK, "jsonp": CALLBACK, "cb": CALLBACK, "webhook": CALLBACK,
    # File
    "file": FILE, "filename": FILE, "filepath": FILE, "document": FILE,
    "doc": FILE, "attachment": FILE, "upload": FILE, "download": FILE,
    # Filesystem
    "path": FILESYSTEM, "dir": FILESYSTEM, "folder": FILESYSTEM,
    "directory": FILESYSTEM, "root": FILESYSTEM, "location": FILESYSTEM,
    # Command
    "cmd": COMMAND, "command": COMMAND, "exec": COMMAND, "run": COMMAND,
    "query_cmd": COMMAND, "ping": COMMAND, "shell": COMMAND, "system": COMMAND,
    # Authentication
    "token": AUTHENTICATION, "jwt": AUTHENTICATION, "auth": AUTHENTICATION,
    "access_token": AUTHENTICATION, "accesstoken": AUTHENTICATION,
    "session": AUTHENTICATION, "sessionid": AUTHENTICATION,
    "session_id": AUTHENTICATION, "sid": AUTHENTICATION, "csrf": AUTHENTICATION,
    "csrf_token": AUTHENTICATION, "xsrf": AUTHENTICATION, "auth_token": AUTHENTICATION,
    # Credential
    "apikey": CREDENTIAL, "api_key": CREDENTIAL, "key": CREDENTIAL,
    "password": CREDENTIAL, "passwd": CREDENTIAL, "pwd": CREDENTIAL,
    "secret": CREDENTIAL, "client_secret": CREDENTIAL, "signature": CREDENTIAL,
    "sig": CREDENTIAL, "hash": CREDENTIAL,
    # Identity
    "email": IDENTITY, "mail": IDENTITY, "username": IDENTITY, "user": IDENTITY,
    "login": IDENTITY, "name": IDENTITY, "phone": IDENTITY, "mobile": IDENTITY,
    "firstname": IDENTITY, "lastname": IDENTITY,
    # Search
    "search": SEARCH, "query": SEARCH, "q": SEARCH, "keyword": SEARCH,
    "keywords": SEARCH, "term": SEARCH, "s": SEARCH, "filter": SEARCH,
    # Localization
    "lang": LOCALIZATION, "language": LOCALIZATION, "locale": LOCALIZATION,
    "country": LOCALIZATION, "region": LOCALIZATION, "currency": LOCALIZATION,
    "tz": LOCALIZATION, "timezone": LOCALIZATION,
    # OAuth
    "state": OAUTH, "code": OAUTH, "grant_type": OAUTH, "response_type": OAUTH,
    "client_id": OAUTH, "scope": OAUTH, "nonce": OAUTH, "id_token": OAUTH,
    "redirect_uri": OAUTH,
}

# Substring rules (ordered by priority) — used when no exact match. Each is a
# ``(substring, type)`` pair; the first substring found in the name wins.
_TYPE_RULES: tuple[tuple[str, str], ...] = (
    ("redirect", REDIRECT), ("return", REDIRECT), ("callback", CALLBACK),
    ("password", CREDENTIAL), ("passwd", CREDENTIAL), ("secret", CREDENTIAL),
    ("apikey", CREDENTIAL), ("api_key", CREDENTIAL),
    ("token", AUTHENTICATION), ("session", AUTHENTICATION), ("csrf", AUTHENTICATION),
    ("jwt", AUTHENTICATION), ("auth", AUTHENTICATION),
    ("email", IDENTITY), ("username", IDENTITY), ("user", IDENTITY),
    ("filepath", FILE), ("filename", FILE), ("file", FILE), ("upload", FILE),
    ("path", FILESYSTEM), ("folder", FILESYSTEM), ("dir", FILESYSTEM),
    ("cmd", COMMAND), ("command", COMMAND), ("exec", COMMAND),
    ("url", URL_TYPE), ("uri", URL_TYPE), ("link", URL_TYPE), ("domain", URL_TYPE),
    ("search", SEARCH), ("query", SEARCH), ("keyword", SEARCH),
    ("page", PAGINATION), ("limit", PAGINATION), ("offset", PAGINATION),
    ("sort", SORTING), ("order", SORTING),
    ("lang", LOCALIZATION), ("locale", LOCALIZATION),
    ("_id", IDENTIFIER), ("id", IDENTIFIER),
)


def classify_parameter(name: str) -> str:
    """Classify a parameter name into a :data:`ParameterType` string.

    Accepts either a raw or already-normalized name — it normalizes internally so
    callers can pass either. Falls back to :data:`UNKNOWN` when nothing matches.
    """
    normalized = normalize_parameter(name)
    if not normalized:
        return UNKNOWN
    exact = _EXACT_TYPES.get(normalized)
    if exact:
        return exact
    for substring, ptype in _TYPE_RULES:
        if substring in normalized:
            return ptype
    return UNKNOWN


def type_label(ptype: str) -> str:
    meta = PARAMETER_TYPE_META.get(ptype)
    return meta.label if meta else ptype


def all_parameter_types() -> list[dict]:
    """Serializable parameter-type metadata for the API / frontend legend."""
    return [
        {"type": m.type, "label": m.label, "interesting": m.interesting}
        for m in PARAMETER_TYPE_META.values()
    ]
