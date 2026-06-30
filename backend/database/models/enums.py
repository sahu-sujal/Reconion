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
    TECHNOLOGY = "TECHNOLOGY"
    SCREENSHOT = "SCREENSHOT"


class UrlSource(str, enum.Enum):
    """Tools that contribute discovered URLs / JS files (Phase 5)."""

    GAU = "GAU"
    WAYBACKURLS = "WAYBACKURLS"
    KATANA = "KATANA"
    HAKRAWLER = "HAKRAWLER"


class ScanStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
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
