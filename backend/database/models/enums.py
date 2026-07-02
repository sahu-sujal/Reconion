from __future__ import annotations

import enum


class ProgramStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class ScopeType(str, enum.Enum):
    ROOT_DOMAIN = "ROOT_DOMAIN"
    WILDCARD_DOMAIN = "WILDCARD_DOMAIN"
    SUBDOMAIN = "SUBDOMAIN"
    URL = "URL"
    CIDR = "CIDR"
    IP_RANGE = "IP_RANGE"


class AssetType(str, enum.Enum):
    SUBDOMAIN = "SUBDOMAIN"
    HOST = "HOST"
    URL = "URL"
    JS = "JS"
    CLOUD = "CLOUD"
    IP = "IP"
    PORT = "PORT"


class FindingSeverity(str, enum.Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class FindingStatus(str, enum.Enum):
    NEW = "NEW"
    REVIEWING = "REVIEWING"
    CONFIRMED = "CONFIRMED"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    CLOSED = "CLOSED"


class ScanType(str, enum.Enum):
    SUBDOMAIN = "SUBDOMAIN"
    DNS = "DNS"
    HTTP = "HTTP"
    PORT = "PORT"
    URL = "URL"
    JS = "JS"
    CONTENT_DISCOVERY = "CONTENT_DISCOVERY"
    JS_ENDPOINT = "JS_ENDPOINT"
    JS_SECRET = "JS_SECRET"
    TECHNOLOGY = "TECHNOLOGY"
    SCREENSHOT = "SCREENSHOT"


class UrlSource(str, enum.Enum):
    """Tools that contribute discovered URLs / JS files (Phase 5)."""

    GAU = "GAU"
    WAYBACKURLS = "WAYBACKURLS"
    KATANA = "KATANA"
    HAKRAWLER = "HAKRAWLER"
    SUBJS = "SUBJS"


class EndpointTool(str, enum.Enum):
    """JavaScript endpoint-extraction tools (Phase 6.1).

    New extractors (JSLUICE, MANTRA, AST_PARSER, …) can be appended here and
    wired into the worker without any schema change — ``discovery_tools`` is a
    free-form JSON array of these labels.
    """

    LINKFINDER = "LINKFINDER"
    XNLINKFINDER = "XNLINKFINDER"
    JSLUICE = "JSLUICE"


class DiscoverySource(str, enum.Enum):
    """How an endpoint entered the inventory (Phase 6.1).

    Only ``JS_DISCOVERY`` is produced today; the remaining values are reserved
    so later phases can attribute endpoints to their origin without a migration.
    """

    JS_DISCOVERY = "JS_DISCOVERY"
    URL_DISCOVERY = "URL_DISCOVERY"
    API_DISCOVERY = "API_DISCOVERY"
    MANUAL = "MANUAL"


class SecretTool(str, enum.Enum):
    """JavaScript secret-discovery scanners (Phase 6.2).

    New scanners can be appended and wired into the worker without any schema
    change — ``discovery_tools`` on js_secrets is a free-form JSON array.
    """

    SECRETFINDER = "SECRETFINDER"
    MANTRA = "MANTRA"
    NUCLEI_EXPOSURES = "NUCLEI_EXPOSURES"


class SecretSeverity(str, enum.Enum):
    """Severity assigned to a discovered secret (Phase 6.2)."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class SecretType(str, enum.Enum):
    """Canonical secret categories (Phase 6.2).

    Stored as a plain string on js_secrets so new types can be added here without
    a migration. ``UNKNOWN`` is the catch-all for anything a scanner flags that
    doesn't map to a known category.
    """

    AWS_ACCESS_KEY = "AWS_ACCESS_KEY"
    AWS_SECRET_KEY = "AWS_SECRET_KEY"
    AWS_SESSION_TOKEN = "AWS_SESSION_TOKEN"
    GOOGLE_API_KEY = "GOOGLE_API_KEY"
    GOOGLE_OAUTH_CLIENT = "GOOGLE_OAUTH_CLIENT"
    GOOGLE_OAUTH_SECRET = "GOOGLE_OAUTH_SECRET"
    FIREBASE_API_KEY = "FIREBASE_API_KEY"
    FIREBASE_CONFIG = "FIREBASE_CONFIG"
    STRIPE_SECRET_KEY = "STRIPE_SECRET_KEY"
    STRIPE_PUBLIC_KEY = "STRIPE_PUBLIC_KEY"
    SLACK_TOKEN = "SLACK_TOKEN"
    DISCORD_TOKEN = "DISCORD_TOKEN"
    GITHUB_TOKEN = "GITHUB_TOKEN"
    JWT = "JWT"
    BEARER_TOKEN = "BEARER_TOKEN"
    ACCESS_TOKEN = "ACCESS_TOKEN"
    REFRESH_TOKEN = "REFRESH_TOKEN"
    API_KEY = "API_KEY"
    CLIENT_SECRET = "CLIENT_SECRET"
    PRIVATE_KEY = "PRIVATE_KEY"
    RSA_PRIVATE_KEY = "RSA_PRIVATE_KEY"
    OPENSSH_PRIVATE_KEY = "OPENSSH_PRIVATE_KEY"
    SSH_PRIVATE_KEY = "SSH_PRIVATE_KEY"
    DATABASE_URL = "DATABASE_URL"
    MYSQL_URI = "MYSQL_URI"
    POSTGRES_URI = "POSTGRES_URI"
    MONGODB_URI = "MONGODB_URI"
    REDIS_URI = "REDIS_URI"
    ELASTICSEARCH_URI = "ELASTICSEARCH_URI"
    WEBHOOK = "WEBHOOK"
    BASIC_AUTH = "BASIC_AUTH"
    UNKNOWN = "UNKNOWN"


class ScanStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ToolExecutionStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class NotificationChannel(str, enum.Enum):
    EMAIL = "EMAIL"
    SLACK = "SLACK"
    TEAMS = "TEAMS"
    WEBHOOK = "WEBHOOK"
