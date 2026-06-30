"""Discord notification helpers.

Two entry points:
    send_discord_direct()          — low-level: send any title+message, synchronous
    send_scan_complete_notification() — high-level: structured scan-complete embed

Neither function raises; all errors are logged as warnings.
"""

from __future__ import annotations

import json
import logging
import os
import uuid as _uuid_module
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.celery_app import celery_app

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"


# ------------------------------------------------------------------ #
# Internal helpers                                                      #
# ------------------------------------------------------------------ #

def _get_webhook_url() -> str | None:
    return os.getenv("DISCORD_WEBHOOK_URL")


def _send_webhook(webhook_url: str, payload_bytes: bytes) -> None:
    """POST JSON payload to a Discord webhook."""
    request = Request(
        webhook_url,
        data=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
        },
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        response.read()


def _send_webhook_with_file(
    webhook_url: str,
    payload: dict,
    filename: str,
    file_content: str,
) -> None:
    """POST a Discord webhook with a file attachment (multipart/form-data)."""
    boundary = "FormBoundary" + _uuid_module.uuid4().hex

    parts: list[bytes] = []

    # Part 1 — JSON payload
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(b'Content-Disposition: form-data; name="payload_json"\r\n')
    parts.append(b"Content-Type: application/json\r\n\r\n")
    parts.append(json.dumps(payload).encode("utf-8"))
    parts.append(b"\r\n")

    # Part 2 — text file
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        f'Content-Disposition: form-data; name="file[0]"; filename="{filename}"\r\n'.encode()
    )
    parts.append(b"Content-Type: text/plain; charset=utf-8\r\n\r\n")
    parts.append(file_content.encode("utf-8"))
    parts.append(b"\r\n")

    # Closing boundary
    parts.append(f"--{boundary}--\r\n".encode())

    body = b"".join(parts)
    request = Request(
        webhook_url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": DEFAULT_USER_AGENT,
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        response.read()


# ------------------------------------------------------------------ #
# Low-level API                                                         #
# ------------------------------------------------------------------ #

def send_discord_direct(
    webhook_url: str | None,
    title: str,
    message: str,
) -> None:
    """Send a plain title+message Discord notification synchronously.

    Safe to call from any context — silently skips if no webhook URL is
    configured, and never raises (logs warnings on failure instead).
    """
    resolved_url = webhook_url or _get_webhook_url()
    if not resolved_url:
        logger.warning("Discord webhook URL not configured — notification skipped")
        return
    payload = json.dumps({"content": f"**{title}**\n{message}"}).encode("utf-8")
    try:
        _send_webhook(resolved_url, payload)
        logger.info("Discord notification sent: %s", title)
    except HTTPError as exc:
        logger.warning("Discord webhook HTTP error: %s %s", exc.code, exc.reason)
    except URLError as exc:
        logger.warning("Discord webhook URL error: %s", exc.reason)
    except Exception as exc:
        logger.warning("Discord notification failed: %s", exc)


# ------------------------------------------------------------------ #
# High-level scan-complete notification                                 #
# ------------------------------------------------------------------ #

def send_scan_complete_notification(
    webhook_url: str | None,
    program_name: str,
    scope_target: str,
    metrics,           # ScanMetrics dataclass — avoid circular import
    new_subdomains: list[str],
) -> bool:
    """Send a single structured Discord embed summarising the completed scan.

    - One message per scan (never one-per-asset).
    - Attaches ``new_assets.txt`` when new subdomains exist.
    - Never raises.
    """
    resolved_url = webhook_url or _get_webhook_url()
    if not resolved_url:
        logger.warning("Discord webhook URL not configured — scan notification skipped")
        return

    has_new = metrics.new_count > 0
    color = 0x00FF7F if has_new else 0x5865F2   # green for new finds, blurple otherwise
    title = (
        f"\U0001f195 {metrics.new_count} New Asset(s) Found!"
        if has_new
        else "\U0001f50d Recon Completed — No New Assets"
    )

    # Metrics table (fixed-width for Discord code block)
    tool_block = "\n".join([
        "```",
        f"Subfinder     {metrics.subfinder_raw:>7} raw   {metrics.subfinder_count:>7} in-scope",
        f"Assetfinder   {metrics.assetfinder_raw:>7} raw   {metrics.assetfinder_count:>7} in-scope",
        f"Knockpy       {metrics.knockpy_raw:>7} raw   {metrics.knockpy_count:>7} in-scope",
        f"DNSGen        {metrics.dnsgen_raw:>7} raw   {metrics.dnsgen_count:>7} in-scope",
        f"Chaos         {metrics.chaos_raw:>7} raw   {metrics.chaos_count:>7} in-scope",
        f"CRT.SH        {metrics.crtsh_raw:>7} raw   {metrics.crtsh_count:>7} in-scope",
        f"Findomain     {metrics.findomain_raw:>7} raw   {metrics.findomain_count:>7} in-scope",
        f"─────────────────────────────────────",
        f"Merged (raw)  {metrics.merged_count:>7}",
        f"Unique        {metrics.unique_count:>7}",
        f"New assets    {metrics.new_count:>7}",
        f"Existing      {metrics.existing_count:>7}",
        "```",
    ])

    desc_lines = [
        f"**Program:** {program_name}",
        f"**Scope:** `{scope_target}`",
        "",
        "**Metrics:**",
        tool_block,
    ]

    if new_subdomains:
        top = sorted(new_subdomains)[:10]
        desc_lines += [
            "",
            f"**Top {len(top)} New Subdomains:**",
            "```",
            *top,
            "```",
        ]
        if metrics.new_count > 10:
            desc_lines.append(
                f"*...and {metrics.new_count - 10} more — see scan diff file for the full list.*"
            )

    embed = {
        "title": title,
        "description": "\n".join(desc_lines),
        "color": color,
    }
    payload = {"embeds": [embed]}

    try:
        if new_subdomains:
            file_content = "\n".join(sorted(new_subdomains))
            _send_webhook_with_file(resolved_url, payload, "new_assets_sample.txt", file_content)
        else:
            _send_webhook(resolved_url, json.dumps(payload).encode("utf-8"))
        logger.info("Discord scan-complete notification sent: %s/%s", program_name, scope_target)
        return True
    except HTTPError as exc:
        logger.warning("Discord webhook HTTP error %s %s — retrying without attachment", exc.code, exc.reason)
        try:
            _send_webhook(resolved_url, json.dumps(payload).encode("utf-8"))
            return True
        except Exception as exc2:
            logger.warning("Discord notification failed: %s", exc2)
    except URLError as exc:
        logger.warning("Discord webhook URL error: %s", exc.reason)
    except Exception as exc:
        logger.warning("Discord notification failed: %s", exc)
    return False


# ------------------------------------------------------------------ #
# DNS scan-complete notification                                         #
# ------------------------------------------------------------------ #

def send_dns_scan_notification(
    webhook_url: str | None,
    program_name: str,
    scope_target: str,
    metrics,              # DnsMetrics dataclass — avoid circular import
) -> bool:
    """Send a structured Discord embed for a completed DNS scan.

    Never raises.
    """
    resolved_url = webhook_url or _get_webhook_url()
    if not resolved_url:
        logger.warning("Discord webhook URL not configured — DNS notification skipped")
        return False

    has_new = metrics.new_hosts > 0
    color = 0x00BFFF if has_new else 0x5865F2
    title = (
        f"\U0001f310 {metrics.new_hosts} New Host(s) Resolved!"
        if has_new
        else "\U0001f310 DNS Scan Complete — No New Hosts"
    )

    block = "\n".join([
        "```",
        f"Subdomains resolved   {metrics.dnsx_input:>7}",
        f"Hosts resolved        {metrics.dnsx_resolved:>7}",
        f"New hosts             {metrics.new_hosts:>7}",
        f"Existing hosts        {metrics.existing_hosts:>7}",
        f"DNS records inserted  {metrics.dns_records_inserted:>7}",
        "```",
    ])

    embed = {
        "title": title,
        "description": "\n".join([
            f"**Program:** {program_name}",
            f"**Scope:** `{scope_target}`",
            "",
            "**Metrics:**",
            block,
        ]),
        "color": color,
    }
    payload = {"embeds": [embed]}

    try:
        _send_webhook(resolved_url, json.dumps(payload).encode("utf-8"))
        logger.info("Discord DNS scan notification sent: %s/%s", program_name, scope_target)
        return True
    except HTTPError as exc:
        logger.warning("Discord webhook HTTP error %s %s", exc.code, exc.reason)
    except URLError as exc:
        logger.warning("Discord webhook URL error: %s", exc.reason)
    except Exception as exc:
        logger.warning("Discord DNS notification failed: %s", exc)
    return False


# ------------------------------------------------------------------ #
# HTTP scan-complete notification                                        #
# ------------------------------------------------------------------ #

def send_http_scan_notification(
    webhook_url: str | None,
    program_name: str,
    scope_target: str,
    metrics,              # HttpMetrics dataclass — avoid circular import
) -> bool:
    """Send a structured Discord embed for a completed HTTP scan.

    Never raises.
    """
    resolved_url = webhook_url or _get_webhook_url()
    if not resolved_url:
        logger.warning("Discord webhook URL not configured — HTTP notification skipped")
        return False

    has_new = metrics.httpx_live > 0
    color = 0x00FF7F if has_new else 0x5865F2
    title = (
        f"\U0001f4bb {metrics.httpx_live} Live Host(s) Found!"
        if has_new
        else "\U0001f4bb HTTP Scan Complete — No Live Hosts"
    )

    # Status code distribution block
    dist = metrics.status_distribution
    dist_lines = [f"  {sc}: {cnt}" for sc, cnt in sorted(dist.items())]
    dist_block = "\n".join(["```", *dist_lines, "```"]) if dist_lines else "*(none)*"

    block = "\n".join([
        "```",
        f"Hosts probed          {metrics.httpx_input:>7}",
        f"Live hosts            {metrics.httpx_live:>7}",
        f"HTTP responses saved  {metrics.http_responses_inserted:>7}",
        f"Technologies found    {metrics.technologies_found:>7}",
        "```",
    ])

    embed = {
        "title": title,
        "description": "\n".join([
            f"**Program:** {program_name}",
            f"**Scope:** `{scope_target}`",
            "",
            "**Metrics:**",
            block,
            "",
            "**Status Distribution:**",
            dist_block,
        ]),
        "color": color,
    }
    payload = {"embeds": [embed]}

    try:
        _send_webhook(resolved_url, json.dumps(payload).encode("utf-8"))
        logger.info("Discord HTTP scan notification sent: %s/%s", program_name, scope_target)
        return True
    except HTTPError as exc:
        logger.warning("Discord webhook HTTP error %s %s", exc.code, exc.reason)
    except URLError as exc:
        logger.warning("Discord webhook URL error: %s", exc.reason)
    except Exception as exc:
        logger.warning("Discord HTTP notification failed: %s", exc)
    return False


# ------------------------------------------------------------------ #
# Content discovery scan-complete notification (Phase 5)                #
# ------------------------------------------------------------------ #

def send_content_discovery_notification(
    webhook_url: str | None,
    program_name: str,
    scope_target: str,
    metrics,              # ContentDiscoveryMetrics dataclass — avoid circular import
    duration_seconds: float,
) -> bool:
    """Send a structured Discord embed for a completed content discovery scan.

    Never raises.
    """
    resolved_url = webhook_url or _get_webhook_url()
    if not resolved_url:
        logger.warning("Discord webhook URL not configured — content discovery notification skipped")
        return False

    has_new = metrics.new_urls > 0 or metrics.new_js > 0
    color = 0x00FF7F if has_new else 0x5865F2

    mins, secs = divmod(int(duration_seconds), 60)
    duration_str = f"{mins}m {secs}s" if mins else f"{secs}s"

    tool_block = "\n".join([
        "```",
        f"GAU           {metrics.gau_count:>9}",
        f"Waybackurls   {metrics.waybackurls_count:>9}",
        f"Katana        {metrics.katana_count:>9}",
        f"Hakrawler     {metrics.hakrawler_count:>9}",
        "─────────────────────────",
        f"Total URLs    {metrics.total_urls:>9}",
        f"New URLs      {metrics.new_urls:>9}",
        f"Total JS      {metrics.total_js:>9}",
        f"New JS        {metrics.new_js:>9}",
        "```",
    ])

    embed = {
        "title": "\U0001f4e1 Content Discovery Complete",
        "description": "\n".join([
            f"**Program:** {program_name}",
            f"**Scope:** `{scope_target}`",
            "",
            f"**New URLs:** {metrics.new_urls:,}",
            f"**New JS Files:** {metrics.new_js:,}",
            f"**Duration:** {duration_str}",
            "",
            "**Tool breakdown (raw URLs):**",
            tool_block,
        ]),
        "color": color,
    }
    payload = {"embeds": [embed]}

    try:
        _send_webhook(resolved_url, json.dumps(payload).encode("utf-8"))
        logger.info("Discord content discovery notification sent: %s/%s", program_name, scope_target)
        return True
    except HTTPError as exc:
        logger.warning("Discord webhook HTTP error %s %s", exc.code, exc.reason)
    except URLError as exc:
        logger.warning("Discord webhook URL error: %s", exc.reason)
    except Exception as exc:
        logger.warning("Discord content discovery notification failed: %s", exc)
    return False


# ------------------------------------------------------------------ #
# Celery async wrapper (kept for backward compat)                       #
# ------------------------------------------------------------------ #

@celery_app.task(name="workers.notification.discord_worker.send_discord_notification")
def send_discord_notification(
    webhook_url: str | None,
    title: str,
    message: str,
) -> None:
    """Async Celery wrapper — delegates to send_discord_direct."""
    send_discord_direct(webhook_url, title, message)
