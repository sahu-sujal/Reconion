"""Secret normalization, classification, severity + fingerprint engine (Phase 6.2).

Shared by every secret scanner wrapper and the secret worker so that:

  * each scanner's raw type label is mapped to a **canonical** ``SecretType``
    (``classify_secret_type``) — scanners disagree on names ("aws_access_key" vs
    "AWS Access Key" vs "amazon-key");
  * the raw value is **normalized** for dedup (``normalize_secret`` — trims,
    collapses whitespace) while the *original* value is always stored unmasked;
  * a stable **fingerprint** = ``sha256(type + '|' + normalized)`` is the dedup
    key — the same secret from different tools/files collapses to one record;
  * each type gets a **configurable severity** (``severity_for``).

Severity rules and type patterns live in module-level dicts so new types /
severities are a one-line change, no code restructuring and no schema change.
"""
from __future__ import annotations

import hashlib
import re

from database.models.enums import SecretSeverity, SecretType

# ---------------------------------------------------------------------------
# Severity mapping (configurable — override via SECRET_SEVERITY_OVERRIDES)
# ---------------------------------------------------------------------------

_SEVERITY: dict[str, str] = {
    # Critical — full compromise / credential material
    SecretType.PRIVATE_KEY.value: SecretSeverity.CRITICAL.value,
    SecretType.RSA_PRIVATE_KEY.value: SecretSeverity.CRITICAL.value,
    SecretType.OPENSSH_PRIVATE_KEY.value: SecretSeverity.CRITICAL.value,
    SecretType.SSH_PRIVATE_KEY.value: SecretSeverity.CRITICAL.value,
    SecretType.AWS_SECRET_KEY.value: SecretSeverity.CRITICAL.value,
    SecretType.AWS_SESSION_TOKEN.value: SecretSeverity.CRITICAL.value,
    SecretType.STRIPE_SECRET_KEY.value: SecretSeverity.CRITICAL.value,
    SecretType.DATABASE_URL.value: SecretSeverity.CRITICAL.value,
    SecretType.MYSQL_URI.value: SecretSeverity.CRITICAL.value,
    SecretType.POSTGRES_URI.value: SecretSeverity.CRITICAL.value,
    SecretType.MONGODB_URI.value: SecretSeverity.CRITICAL.value,
    SecretType.REDIS_URI.value: SecretSeverity.CRITICAL.value,
    SecretType.ELASTICSEARCH_URI.value: SecretSeverity.CRITICAL.value,
    SecretType.GOOGLE_OAUTH_SECRET.value: SecretSeverity.CRITICAL.value,
    SecretType.CLIENT_SECRET.value: SecretSeverity.CRITICAL.value,
    # High — powerful tokens / access keys
    SecretType.AWS_ACCESS_KEY.value: SecretSeverity.HIGH.value,
    SecretType.SLACK_TOKEN.value: SecretSeverity.HIGH.value,
    SecretType.GITHUB_TOKEN.value: SecretSeverity.HIGH.value,
    SecretType.DISCORD_TOKEN.value: SecretSeverity.HIGH.value,
    SecretType.BASIC_AUTH.value: SecretSeverity.HIGH.value,
    SecretType.REFRESH_TOKEN.value: SecretSeverity.HIGH.value,
    # Medium — session / bearer tokens, generic API keys
    SecretType.JWT.value: SecretSeverity.MEDIUM.value,
    SecretType.BEARER_TOKEN.value: SecretSeverity.MEDIUM.value,
    SecretType.ACCESS_TOKEN.value: SecretSeverity.MEDIUM.value,
    SecretType.API_KEY.value: SecretSeverity.MEDIUM.value,
    SecretType.GOOGLE_API_KEY.value: SecretSeverity.MEDIUM.value,
    SecretType.GOOGLE_OAUTH_CLIENT.value: SecretSeverity.MEDIUM.value,
    SecretType.WEBHOOK.value: SecretSeverity.MEDIUM.value,
    # Low — public / config keys
    SecretType.FIREBASE_API_KEY.value: SecretSeverity.LOW.value,
    SecretType.FIREBASE_CONFIG.value: SecretSeverity.LOW.value,
    SecretType.STRIPE_PUBLIC_KEY.value: SecretSeverity.LOW.value,
}
_DEFAULT_SEVERITY = SecretSeverity.INFO.value


def severity_for(secret_type: str) -> str:
    """Return the configured severity for a canonical secret type."""
    return _SEVERITY.get(secret_type, _DEFAULT_SEVERITY)


# ---------------------------------------------------------------------------
# Canonical classification
# ---------------------------------------------------------------------------
#
# Two-stage: first try to match a scanner's *label* to a canonical type, then
# fall back to matching the *value* against known patterns. Patterns are ordered
# most-specific first.

# Substrings in a scanner's raw type label → canonical type.
_LABEL_MAP: list[tuple[str, str]] = [
    ("aws_secret", SecretType.AWS_SECRET_KEY.value),
    ("aws secret", SecretType.AWS_SECRET_KEY.value),
    ("aws_session", SecretType.AWS_SESSION_TOKEN.value),
    ("aws_access", SecretType.AWS_ACCESS_KEY.value),
    ("amazon_aws_access", SecretType.AWS_ACCESS_KEY.value),
    ("aws", SecretType.AWS_ACCESS_KEY.value),
    ("google_oauth_secret", SecretType.GOOGLE_OAUTH_SECRET.value),
    ("google_oauth", SecretType.GOOGLE_OAUTH_CLIENT.value),
    ("google_api", SecretType.GOOGLE_API_KEY.value),
    ("google", SecretType.GOOGLE_API_KEY.value),
    ("firebase_config", SecretType.FIREBASE_CONFIG.value),
    ("firebase", SecretType.FIREBASE_API_KEY.value),
    ("stripe_secret", SecretType.STRIPE_SECRET_KEY.value),
    ("stripe_public", SecretType.STRIPE_PUBLIC_KEY.value),
    ("stripe", SecretType.STRIPE_SECRET_KEY.value),
    ("slack", SecretType.SLACK_TOKEN.value),
    ("discord", SecretType.DISCORD_TOKEN.value),
    ("github", SecretType.GITHUB_TOKEN.value),
    ("jwt", SecretType.JWT.value),
    ("bearer", SecretType.BEARER_TOKEN.value),
    ("refresh_token", SecretType.REFRESH_TOKEN.value),
    ("access_token", SecretType.ACCESS_TOKEN.value),
    ("client_secret", SecretType.CLIENT_SECRET.value),
    ("rsa_private", SecretType.RSA_PRIVATE_KEY.value),
    ("openssh", SecretType.OPENSSH_PRIVATE_KEY.value),
    ("ssh_private", SecretType.SSH_PRIVATE_KEY.value),
    ("private_key", SecretType.PRIVATE_KEY.value),
    ("private key", SecretType.PRIVATE_KEY.value),
    ("mysql", SecretType.MYSQL_URI.value),
    ("postgres", SecretType.POSTGRES_URI.value),
    ("mongodb", SecretType.MONGODB_URI.value),
    ("mongo", SecretType.MONGODB_URI.value),
    ("redis", SecretType.REDIS_URI.value),
    ("elasticsearch", SecretType.ELASTICSEARCH_URI.value),
    ("database_url", SecretType.DATABASE_URL.value),
    ("database", SecretType.DATABASE_URL.value),
    ("basic_auth", SecretType.BASIC_AUTH.value),
    ("basic auth", SecretType.BASIC_AUTH.value),
    ("webhook", SecretType.WEBHOOK.value),
    ("api_key", SecretType.API_KEY.value),
    ("apikey", SecretType.API_KEY.value),
    ("api key", SecretType.API_KEY.value),
]

# Value patterns → canonical type (fallback when the label is generic/unknown).
_VALUE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^AKIA[0-9A-Z]{16}$"), SecretType.AWS_ACCESS_KEY.value),
    (re.compile(r"^ASIA[0-9A-Z]{16}$"), SecretType.AWS_SESSION_TOKEN.value),
    (re.compile(r"^gh[pousr]_[A-Za-z0-9]{36,}$"), SecretType.GITHUB_TOKEN.value),
    (re.compile(r"^github_pat_[A-Za-z0-9_]{50,}$"), SecretType.GITHUB_TOKEN.value),
    (re.compile(r"^sk_live_[0-9a-zA-Z]{20,}$"), SecretType.STRIPE_SECRET_KEY.value),
    (re.compile(r"^pk_live_[0-9a-zA-Z]{20,}$"), SecretType.STRIPE_PUBLIC_KEY.value),
    (re.compile(r"^xox[baprs]-[0-9A-Za-z-]{10,}$"), SecretType.SLACK_TOKEN.value),
    (re.compile(r"^AIza[0-9A-Za-z_\-]{35}$"), SecretType.GOOGLE_API_KEY.value),
    (re.compile(r"^[0-9]+-[0-9A-Za-z_]{32}\.apps\.googleusercontent\.com$"),
     SecretType.GOOGLE_OAUTH_CLIENT.value),
    (re.compile(r"^ey[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+$"), SecretType.JWT.value),
    (re.compile(r"-----BEGIN RSA PRIVATE KEY-----"), SecretType.RSA_PRIVATE_KEY.value),
    (re.compile(r"-----BEGIN OPENSSH PRIVATE KEY-----"), SecretType.OPENSSH_PRIVATE_KEY.value),
    (re.compile(r"-----BEGIN (?:EC |DSA )?PRIVATE KEY-----"), SecretType.PRIVATE_KEY.value),
    (re.compile(r"^mongodb(?:\+srv)?://"), SecretType.MONGODB_URI.value),
    (re.compile(r"^mysql://"), SecretType.MYSQL_URI.value),
    (re.compile(r"^postgres(?:ql)?://"), SecretType.POSTGRES_URI.value),
    (re.compile(r"^redis://"), SecretType.REDIS_URI.value),
    (re.compile(r"^https?://[^\s]+@"), SecretType.BASIC_AUTH.value),
    (re.compile(r"^Bearer\s+[A-Za-z0-9._\-]+$", re.IGNORECASE), SecretType.BEARER_TOKEN.value),
]


def classify_secret_type(raw_label: str | None, value: str | None) -> str:
    """Map a scanner's raw type label + value to a canonical ``SecretType``.

    Tries the label first (scanner already categorised it), then falls back to
    value-pattern matching, and finally ``UNKNOWN``.
    """
    label = (raw_label or "").strip().lower()
    if label:
        for needle, canonical in _LABEL_MAP:
            if needle in label:
                return canonical
        # exact enum name match (e.g. a scanner already emits canonical names)
        upper = raw_label.strip().upper().replace(" ", "_").replace("-", "_")
        try:
            return SecretType[upper].value
        except KeyError:
            pass
    if value:
        v = value.strip()
        for pattern, canonical in _VALUE_PATTERNS:
            if pattern.search(v):
                return canonical
    return SecretType.UNKNOWN.value


# ---------------------------------------------------------------------------
# Normalization + fingerprint
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")


def normalize_secret(value: str | None) -> str | None:
    """Canonicalise a secret for dedup — trim + collapse internal whitespace.

    The *original* value is stored separately and unmasked; this is only the
    dedup key input. Returns ``None`` for empty/whitespace-only input.
    """
    if not value:
        return None
    normalized = _WS_RE.sub(" ", value.strip())
    return normalized or None


def fingerprint(secret_type: str, normalized_secret: str) -> str:
    """Stable dedup key: ``sha256(type + '|' + normalized_secret)`` (hex)."""
    data = f"{secret_type}|{normalized_secret}".encode("utf-8", errors="replace")
    return hashlib.sha256(data).hexdigest()


# Obvious non-secret junk scanners sometimes emit (placeholders, examples).
_JUNK = {
    "your_api_key", "api_key", "xxxxxxxx", "changeme", "example",
    "null", "undefined", "true", "false", "test", "todo",
}


def is_probably_valid(value: str | None, secret_type: str) -> bool:
    """Cheap sanity filter to drop obvious placeholder / junk matches."""
    if not value:
        return False
    v = value.strip()
    if len(v) < 6:
        return False
    if v.lower() in _JUNK:
        return False
    # A value that is a single repeated char (xxxx, ****) is a mask/placeholder.
    if len(set(v)) <= 2 and secret_type != SecretType.UNKNOWN.value:
        return False
    return True
