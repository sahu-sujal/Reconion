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
