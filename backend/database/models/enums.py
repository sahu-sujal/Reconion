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
