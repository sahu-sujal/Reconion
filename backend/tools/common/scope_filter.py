from __future__ import annotations


def _root_domain(scope_target: str) -> str:
    """Strip wildcard prefix and normalise case.

    "*.detectify.com"  -> "detectify.com"
    "detectify.com"    -> "detectify.com"
    """
    target = scope_target.strip().lower()
    if target.startswith("*."):
        target = target[2:]
    return target


def is_subdomain_in_scope(subdomain: str, scope_target: str) -> bool:
    """Return True if *subdomain* belongs to the scope target domain.

    Accepted:
        subdomain == root              "detectify.com"     for "detectify.com"
        subdomain ends with .root      "api.detectify.com" for "detectify.com"

    Rejected:
        "linkedin.com", "notdetectify.com", "evildetectify.com", etc.
    """
    root = _root_domain(scope_target)
    name = subdomain.strip().lower()
    return name == root or name.endswith("." + root)


def filter_in_scope(subdomains: list[str], scope_target: str) -> list[str]:
    """Return only the entries that belong to scope_target's domain."""
    return [s for s in subdomains if is_subdomain_in_scope(s, scope_target)]


def host_of_url(url: str | None) -> str | None:
    """Extract the host (authority, no port) from a URL string, or None."""
    if not url:
        return None
    from urllib.parse import urlsplit

    try:
        netloc = urlsplit(url).netloc
    except ValueError:
        return None
    if not netloc:
        return None
    netloc = netloc.rsplit("@", 1)[-1]  # strip any userinfo
    return netloc or None


def filter_rows_in_scope(
    rows: list,
    scope_target: str | None,
    host_key: str = "host",
    url_key: str | None = None,
) -> list:
    """Drop rows whose host is out of scope (persistence guard).

    The host comes from ``host_key`` if present, else it is derived from
    ``url_key`` (for tables like ``js_files`` that store only the URL). Used at
    the repository layer as a final, caller-independent safety net so an
    out-of-scope URL / JS file / endpoint can never be written regardless of
    which code path produced it. If *scope_target* is falsy the rows pass
    through unchanged (scope unknown → don't silently drop everything).
    """
    if not scope_target:
        return rows

    def _host(row) -> str | None:
        h = row.get(host_key)
        if h:
            return h
        if url_key:
            return host_of_url(row.get(url_key))
        return None

    return [r for r in rows if is_host_in_scope(_host(r), scope_target)]


def is_host_in_scope(host: str | None, scope_target: str) -> bool:
    """Return True if a URL/endpoint *host* is in scope for *scope_target*.

    Bug-bounty scope rule: a host is in scope when it equals the scope root
    domain or is a subdomain of it — so a ``tesla.com`` scope keeps
    ``tesla.com`` and ``api.tesla.com`` but rejects third-party / CDN hosts like
    ``cdn.example.com`` or ``fonts.googleapis.com`` that an in-scope JS file may
    reference. Out-of-scope assets can't be reported, so they're never stored.

    The *host* may carry a port (``api.tesla.com:8443``) — the port is ignored.
    IPv6 literals and empty hosts are treated as out of scope (no domain scope
    applies to them here).
    """
    if not host:
        return False
    name = host.strip().lower()
    if name.startswith("["):  # IPv6 literal — not a domain-scope match
        return False
    if ":" in name:  # strip trailing :port
        name = name.rsplit(":", 1)[0]
    return is_subdomain_in_scope(name, scope_target)
