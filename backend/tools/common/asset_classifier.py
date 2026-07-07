"""Asset Classification Engine — Phase 6.3.

Determines **what type of asset** a URL / endpoint / JS file is, using only data
already stored (extension, path, host, parameters). *No network requests are made.*

This is NOT GF classification, NOT vulnerability classification, NOT technology
detection — it only answers "what kind of thing is this?" so later phases
(Parameter Discovery, GF, Vulnerability Scanning) can operate on the right subset.

Design
------
The taxonomy is a flat, ordered list of :class:`CategoryRule` objects. Classifying
an asset walks the rules in priority order and returns the first match. Adding a
new category is a one-line append here — no schema change, no engine change, and
the UI reads categories from :data:`ASSET_CATEGORY_META` so it extends too.

The boolean flags (``is_static``, ``is_api`` …) are derived from the matched
category's ``traits`` — they are denormalized onto each row so the Asset Explorer
and later phases can filter with a plain indexed boolean instead of re-deriving.

This module is the **single Python source of truth** and is intentionally kept in
lock-step with ``frontend/src/lib/huntCategories.js`` (same keyword taxonomy).
"""
from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from urllib.parse import urlsplit

# --------------------------------------------------------------------------- #
# Asset categories (stable string keys stored in the DB)                        #
# --------------------------------------------------------------------------- #

# API / dynamic
API = "API"
DYNAMIC_PAGE = "DYNAMIC_PAGE"
WEB_PAGE = "WEB_PAGE"
# Code
JAVASCRIPT = "JAVASCRIPT"
SCRIPT = "SCRIPT"
# Static
STYLESHEET = "STYLESHEET"
IMAGE = "IMAGE"
FONT = "FONT"
VIDEO = "VIDEO"
AUDIO = "AUDIO"
STATIC = "STATIC"
# Documents
DOCUMENT = "DOCUMENT"
# Archives
ARCHIVE = "ARCHIVE"
# Configuration
CONFIGURATION = "CONFIGURATION"
# Credentials — certificates & private keys (highly sensitive)
CREDENTIAL = "CREDENTIAL"
# Logs & backups (sensitive)
LOG_BACKUP = "LOG_BACKUP"
# Path-pattern categories
AUTHENTICATION = "AUTHENTICATION"
ADMINISTRATION = "ADMINISTRATION"
UPLOAD = "UPLOAD"
DOWNLOAD = "DOWNLOAD"
DOCUMENTATION = "DOCUMENTATION"
MONITORING = "MONITORING"
CLOUD = "CLOUD"
# Fallback
UNKNOWN = "UNKNOWN"


# --------------------------------------------------------------------------- #
# Trait flags — denormalized booleans derived from the matched category         #
# --------------------------------------------------------------------------- #

TRAIT_FLAGS = (
    "is_static",
    "is_dynamic",
    "is_api",
    "is_document",
    "is_script",
    "is_archive",
    "is_configuration",
    "is_backup",
    "is_credential",
)


@dataclass(frozen=True)
class CategoryMeta:
    """Presentation + trait metadata for one asset category."""

    category: str
    label: str
    group: str            # coarse grouping used by the Explorer sidebar
    traits: frozenset[str] = frozenset()
    sensitive: bool = False


# Ordered category metadata — also drives the frontend sidebar order.
ASSET_CATEGORY_META: dict[str, CategoryMeta] = {
    API: CategoryMeta(API, "APIs", "Dynamic", frozenset({"is_api", "is_dynamic"})),
    DYNAMIC_PAGE: CategoryMeta(DYNAMIC_PAGE, "Dynamic Pages", "Dynamic", frozenset({"is_dynamic"})),
    WEB_PAGE: CategoryMeta(WEB_PAGE, "Web Pages", "Pages"),
    JAVASCRIPT: CategoryMeta(JAVASCRIPT, "JavaScript", "Code", frozenset({"is_static", "is_script"})),
    SCRIPT: CategoryMeta(SCRIPT, "Scripts", "Code", frozenset({"is_script"}), sensitive=True),
    STYLESHEET: CategoryMeta(STYLESHEET, "Stylesheets", "Static", frozenset({"is_static"})),
    IMAGE: CategoryMeta(IMAGE, "Images", "Static", frozenset({"is_static"})),
    FONT: CategoryMeta(FONT, "Fonts", "Static", frozenset({"is_static"})),
    VIDEO: CategoryMeta(VIDEO, "Video", "Static", frozenset({"is_static"})),
    AUDIO: CategoryMeta(AUDIO, "Audio", "Static", frozenset({"is_static"})),
    STATIC: CategoryMeta(STATIC, "Static Assets", "Static", frozenset({"is_static"})),
    DOCUMENT: CategoryMeta(DOCUMENT, "Documents", "Documents", frozenset({"is_document"})),
    ARCHIVE: CategoryMeta(ARCHIVE, "Archives", "Sensitive", frozenset({"is_archive"}), sensitive=True),
    CONFIGURATION: CategoryMeta(CONFIGURATION, "Configuration Files", "Sensitive", frozenset({"is_configuration"}), sensitive=True),
    CREDENTIAL: CategoryMeta(CREDENTIAL, "Credentials & Keys", "Sensitive", frozenset({"is_credential"}), sensitive=True),
    LOG_BACKUP: CategoryMeta(LOG_BACKUP, "Logs & Backups", "Sensitive", frozenset({"is_backup"}), sensitive=True),
    AUTHENTICATION: CategoryMeta(AUTHENTICATION, "Authentication", "Interesting", frozenset({"is_dynamic"})),
    ADMINISTRATION: CategoryMeta(ADMINISTRATION, "Administration", "Interesting", frozenset({"is_dynamic"})),
    UPLOAD: CategoryMeta(UPLOAD, "Upload", "Interesting", frozenset({"is_dynamic"})),
    DOWNLOAD: CategoryMeta(DOWNLOAD, "Download", "Interesting", frozenset({"is_dynamic"})),
    DOCUMENTATION: CategoryMeta(DOCUMENTATION, "Documentation", "Interesting"),
    MONITORING: CategoryMeta(MONITORING, "Monitoring", "Interesting"),
    CLOUD: CategoryMeta(CLOUD, "Cloud", "Interesting"),
    UNKNOWN: CategoryMeta(UNKNOWN, "Unknown", "Unknown"),
}


# --------------------------------------------------------------------------- #
# Extension → (category, mime) tables                                           #
# --------------------------------------------------------------------------- #

# Each maps a normalized (lowercase, no dot) extension to a category.
_EXT_CATEGORY: dict[str, str] = {}
_EXT_MIME: dict[str, str] = {}


def _reg(category: str, mapping: dict[str, str]) -> None:
    for ext, mime in mapping.items():
        _EXT_CATEGORY[ext] = category
        _EXT_MIME[ext] = mime


# Web pages (HTML content — the common non-file, non-API asset)
_reg(WEB_PAGE, {"html": "text/html", "htm": "text/html", "xhtml": "application/xhtml+xml"})
# Stylesheets
_reg(STYLESHEET, {"css": "text/css"})
# JavaScript (its own first-class category per spec)
_reg(JAVASCRIPT, {"js": "text/javascript", "mjs": "text/javascript", "cjs": "text/javascript"})
# Other scripts (sensitive — server/client source)
_reg(SCRIPT, {
    "ts": "text/typescript", "tsx": "text/typescript", "jsx": "text/jsx",
    "sh": "application/x-sh", "ps1": "text/plain", "bat": "text/plain",
    "py": "text/x-python", "rb": "text/x-ruby", "php": "application/x-httpd-php",
    "pl": "text/x-perl",
})
# Images
_reg(IMAGE, {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
    "svg": "image/svg+xml", "webp": "image/webp", "ico": "image/x-icon",
    "bmp": "image/bmp", "tiff": "image/tiff", "avif": "image/avif",
})
# Fonts
_reg(FONT, {
    "woff": "font/woff", "woff2": "font/woff2", "ttf": "font/ttf",
    "otf": "font/otf", "eot": "application/vnd.ms-fontobject",
})
# Video
_reg(VIDEO, {
    "mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime",
    "avi": "video/x-msvideo", "mkv": "video/x-matroska", "m3u8": "application/vnd.apple.mpegurl",
})
# Audio
_reg(AUDIO, {
    "mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg",
    "flac": "audio/flac", "aac": "audio/aac", "m4a": "audio/mp4",
})
# Documents
_reg(DOCUMENT, {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "txt": "text/plain", "csv": "text/csv", "rtf": "application/rtf",
    "odt": "application/vnd.oasis.opendocument.text",
    "md": "text/markdown", "markdown": "text/markdown",
})
# Additional source-code / compiled artifacts (sensitive — server/app source).
_reg(SCRIPT, {
    "java": "text/x-java-source", "class": "application/java-vm",
    "go": "text/x-go", "rs": "text/x-rust", "c": "text/x-c",
    "cpp": "text/x-c++", "cs": "text/x-csharp",
})
# Archives (incl. Java deployables — highly sensitive)
_reg(ARCHIVE, {
    "zip": "application/zip", "rar": "application/vnd.rar",
    "tar": "application/x-tar", "gz": "application/gzip",
    "tgz": "application/gzip", "7z": "application/x-7z-compressed",
    "7zip": "application/x-7z-compressed",
    "bz2": "application/x-bzip2", "xz": "application/x-xz",
    "jar": "application/java-archive", "war": "application/java-archive",
    "ear": "application/java-archive",
})
# Configuration
_reg(CONFIGURATION, {
    "env": "text/plain", "yaml": "application/yaml", "yml": "application/yaml",
    "json": "application/json", "xml": "application/xml", "ini": "text/plain",
    "conf": "text/plain", "toml": "application/toml", "properties": "text/plain",
    "cfg": "text/plain", "config": "text/plain", "plist": "application/xml",
    "gitignore": "text/plain",
})
# Credentials — certificates & private keys (highly sensitive)
_reg(CREDENTIAL, {
    "pem": "application/x-pem-file", "key": "application/pkcs8",
    "crt": "application/x-x509-ca-cert", "cer": "application/x-x509-ca-cert",
    "csr": "application/pkcs10", "p12": "application/x-pkcs12",
    "pfx": "application/x-pkcs12", "keystore": "application/octet-stream",
    "jks": "application/octet-stream", "ppk": "application/octet-stream",
})
# Logs & backups + local databases + hashes/secrets (sensitive)
_reg(LOG_BACKUP, {
    "log": "text/plain", "bak": "application/octet-stream", "old": "application/octet-stream",
    "sql": "application/sql", "db": "application/octet-stream",
    "sqlite": "application/vnd.sqlite3", "sqlite3": "application/vnd.sqlite3",
    "sqlitedb": "application/vnd.sqlite3", "sqlcipher": "application/octet-stream",
    "db3": "application/octet-stream", "dbf": "application/octet-stream",
    "accdb": "application/msaccess", "mdb": "application/msaccess",
    "dump": "application/octet-stream", "backup": "application/octet-stream",
    "swp": "application/octet-stream", "cache": "application/octet-stream",
    "secret": "text/plain", "md5": "text/plain", "sha1": "text/plain",
})


# --------------------------------------------------------------------------- #
# Path-pattern rules (checked when extension is absent/uninformative)           #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class PathRule:
    category: str
    # Substrings matched (lowercased) against the URL path. Any match wins.
    keywords: tuple[str, ...] = ()
    field: tuple[str, ...] = field(default_factory=tuple)


# Ordered by priority — earlier rules win. API path patterns are highest signal.
# Content-page patterns (WEB_PAGE) sit LAST so any technical signal (API, auth,
# admin, docs, …) is preferred over the generic "this is a content page" bucket.
_PATH_RULES: tuple[PathRule, ...] = (
    PathRule(API, ("/api/", "/api.", "/api?", "/v1/", "/v2/", "/v3/", "/rest/", "/graphql",
                   "/gql", "/rpc/", "/jsonrpc", "/ajax/", "/wp-json/", "/.json",
                   "/webhook", "/callback", "/oauth/token")),
    PathRule(DOCUMENTATION, ("swagger", "openapi", "redoc", "api-docs", "apidocs", "/docs/",
                             "/doc/", "swagger-ui", "/hc/", "/help/", "/kb/", "/knowledge",
                             "/support/", "/faq", "readthedocs")),
    PathRule(MONITORING, ("/metrics", "/health", "/healthz", "/ready", "/readyz", "/live",
                          "/livez", "/actuator", "/prometheus", "/status", "/ping")),
    PathRule(AUTHENTICATION, ("/login", "/logout", "/signin", "/sign-in", "/register",
                              "/signup", "/sign-up", "/oauth", "/saml", "/auth", "/sso", "/token")),
    PathRule(ADMINISTRATION, ("/admin", "/administrator", "/dashboard", "/panel",
                              "/manage", "/backend", "/console", "/staff")),
    PathRule(UPLOAD, ("/upload", "/import", "/media/", "/attachment", "/avatar")),
    PathRule(DOWNLOAD, ("/download", "/export", "/report", "/reports")),
    PathRule(CLOUD, ("s3.amazonaws", "s3-", ".s3.", "blob.core.windows", "storage.googleapis",
                     "/storage/", "cloudfront.net", "/cdn/", "digitaloceanspaces")),
    # Generic content pages — marketing / blog / help articles / product pages.
    # Lowest priority so it only catches what nothing else did.
    PathRule(WEB_PAGE, ("/blog", "/learn", "/article", "/articles", "/templates", "/template/",
                        "/pricing", "/product", "/products", "/features", "/feature/",
                        "/case-stud", "/customers", "/customer-", "/solutions", "/resources",
                        "/guide", "/guides", "/tutorial", "/news", "/press", "/about",
                        "/contact", "/terms", "/privacy", "/legal", "/integrations",
                        "/integration/", "/use-cases", "/webinar", "/ebook", "/glossary",
                        "/changelog", "/roadmap", "/community", "/events", "/careers",
                        "/company", "/partners", "/story", "/stories")),
)

# Host prefixes that strongly imply a documentation/help site.
_DOC_HOST_PREFIXES = ("help.", "docs.", "support.", "kb.", "knowledge.", "developer.", "developers.")

# Host-level cloud markers (matched against the host, not the path).
_CLOUD_HOST_MARKERS = (
    "s3.amazonaws.com", "s3-", ".s3.", "blob.core.windows.net",
    "storage.googleapis.com", "cloudfront.net", "digitaloceanspaces.com",
    "r2.cloudflarestorage.com",
)


# --------------------------------------------------------------------------- #
# Result                                                                        #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Classification:
    """The full classification of one asset — maps 1:1 to the DB columns."""

    asset_category: str
    extension: str | None
    mime_type: str | None
    has_parameters: bool
    is_static: bool = False
    is_dynamic: bool = False
    is_api: bool = False
    is_document: bool = False
    is_script: bool = False
    is_archive: bool = False
    is_configuration: bool = False
    is_backup: bool = False
    is_credential: bool = False

    def as_columns(self) -> dict:
        """Return the DB column dict for bulk update."""
        return {
            "asset_category": self.asset_category,
            "extension": self.extension,
            "mime_type": self.mime_type,
            "has_parameters": self.has_parameters,
            "is_static": self.is_static,
            "is_dynamic": self.is_dynamic,
            "is_api": self.is_api,
            "is_document": self.is_document,
            "is_script": self.is_script,
            "is_archive": self.is_archive,
            "is_configuration": self.is_configuration,
            "is_backup": self.is_backup,
            "is_credential": self.is_credential,
        }


# --------------------------------------------------------------------------- #
# Helpers                                                                        #
# --------------------------------------------------------------------------- #

def extract_extension(path_or_url: str) -> str | None:
    """Return the lowercased extension (no dot) of a URL/path, or None.

    Operates on the path component only, so a query string like ``?x=a.b`` never
    leaks into the extension. Multi-part archive extensions collapse to the last
    meaningful part (``.tar.gz`` → ``gz``, already covered by the map).
    """
    if not path_or_url:
        return None
    path = urlsplit(path_or_url).path if "://" in path_or_url or path_or_url.startswith("//") else path_or_url.split("?", 1)[0].split("#", 1)[0]
    base = posixpath.basename(path)
    if "." not in base:
        return None
    ext = base.rsplit(".", 1)[1].strip().lower()
    # Reject non-extension junk (e.g. trailing dot, absurdly long).
    if not ext or len(ext) > 12 or not ext.isalnum():
        return None
    return ext


def _traits_for(category: str) -> dict:
    meta = ASSET_CATEGORY_META.get(category)
    traits = meta.traits if meta else frozenset()
    return {flag: (flag in traits) for flag in TRAIT_FLAGS}


def _has_parameters(url: str, query: str | None) -> bool:
    if query:
        return True
    return "?" in url and "=" in url.split("?", 1)[1]


# Trailing crawler junk to strip for classification (encoded backslash, stray
# backslash/slash, encoded quotes). Repeated until stable.
_TRAILING_JUNK = ("%5c", "%5C", "\\", "%22", "%27", "%2f%22")


def _strip_trailing_junk(url: str) -> str:
    u = url.strip()
    changed = True
    while changed and u:
        changed = False
        low = u.lower()
        for j in _TRAILING_JUNK:
            if low.endswith(j.lower()):
                u = u[: len(u) - len(j)]
                changed = True
                break
    return u


# A path is "page-like" if it has at least one segment made of word-ish chars
# (letters/digits/hyphen/underscore) — i.e. a human-readable route, not just "/".
def _looks_like_page(lower_path: str) -> bool:
    segments = [s for s in lower_path.split("/") if s]
    if not segments:
        return False
    for seg in segments:
        cleaned = seg.replace("-", "").replace("_", "").replace(".", "")
        if cleaned.isalnum() and any(c.isalpha() for c in cleaned):
            return True
    return False


# --------------------------------------------------------------------------- #
# Public API                                                                    #
# --------------------------------------------------------------------------- #

def classify(
    url: str,
    *,
    host: str | None = None,
    path: str | None = None,
    query: str | None = None,
    extension: str | None = None,
    is_js_file: bool = False,
) -> Classification:
    """Classify a single asset from stored data only. Never touches the network.

    Priority:
      1. Explicit JS-file assets → JAVASCRIPT (they came from JS discovery).
      2. Known file extension → its category (documents, archives, images, …).
      3. Cloud host / docs-host markers → CLOUD / DOCUMENTATION.
      4. Path-pattern rules (API, auth, admin, monitoring, content pages, …).
      5. Has query parameters → DYNAMIC_PAGE.
      6. Has a real content path → WEB_PAGE.
      7. Otherwise → UNKNOWN.

    Malformed trailing junk (e.g. an encoded backslash ``%5C`` left by a crawler)
    is stripped for classification only — the caller's stored URL is not mutated.
    """
    url = _strip_trailing_junk(url or "")
    lower_url = url.lower()
    lower_path = (path if path is not None else urlsplit(url).path).lower() if url else ""
    ext = (extension or extract_extension(url)) or None
    if ext:
        ext = ext.lower()
    has_params = _has_parameters(url or "", query)

    def build(category: str, mime: str | None) -> Classification:
        return Classification(
            asset_category=category,
            extension=ext,
            mime_type=mime,
            has_parameters=has_params,
            **_traits_for(category),
        )

    # 1. JS files are their own first-class category.
    if is_js_file or ext in ("js", "mjs", "cjs"):
        return build(JAVASCRIPT, _EXT_MIME.get("js"))

    # 2. Extension-driven categories (highest confidence for files). HTML/htm are
    # deliberately excluded here: an .html URL can still be swagger docs, an admin
    # page, etc., so we let the path rules classify it first and fall back to
    # WEB_PAGE below.
    if ext and ext in _EXT_CATEGORY and _EXT_CATEGORY[ext] != WEB_PAGE:
        return build(_EXT_CATEGORY[ext], _EXT_MIME.get(ext))

    # 3. Cloud storage hosts.
    host_l = (host or "").lower()
    if not host_l and url:
        host_l = urlsplit(url).hostname or ""
    if host_l and any(m in host_l for m in _CLOUD_HOST_MARKERS):
        return build(CLOUD, None)

    # 4. Path-pattern rules (ordered) — technical signals win over generic pages.
    haystack = lower_path or lower_url
    for rule in _PATH_RULES:
        if any(kw in haystack for kw in rule.keywords):
            return build(rule.category, None)

    # 4b. Documentation/help hosts (help.*, docs.*, support.*) — after path rules
    # so an /api on a docs host still classifies as API.
    if host_l.startswith(_DOC_HOST_PREFIXES):
        return build(DOCUMENTATION, None)

    # 5. Dynamic page (has query params but no other signal).
    if has_params:
        return build(DYNAMIC_PAGE, None)

    # 6. Web page: any URL with a real, human-readable content path is a page
    # (not a file, not an API). Only truly path-less/opaque URLs fall through.
    if _looks_like_page(lower_path):
        return build(WEB_PAGE, _EXT_MIME.get("html"))

    # 7. Unknown — no signal at all.
    return build(UNKNOWN, None)


def category_label(category: str) -> str:
    meta = ASSET_CATEGORY_META.get(category)
    return meta.label if meta else category


def all_categories() -> list[dict]:
    """Serializable category metadata for the API / frontend sidebar."""
    return [
        {
            "category": m.category,
            "label": m.label,
            "group": m.group,
            "traits": sorted(m.traits),
            "sensitive": m.sensitive,
        }
        for m in ASSET_CATEGORY_META.values()
    ]
