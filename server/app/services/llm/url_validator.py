"""Validate custom OpenAI-compatible base URLs.

Rules (spec §4.7, §6.2):
- Scheme: only ``http`` or ``https``
- ``http``: only loopback (127.0.0.1, ::1, localhost) and RFC1918 private ranges
  (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
- ``https``: any host
- Reject embedded credentials in the URL (``user:pass@host``)
- Accept optional path prefix (e.g., ``/v1``) — preserved
- Reject query strings and fragments
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit, urlunsplit

# Private network blocks acceptable for plain HTTP base URLs.
_PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),  # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
)


class InvalidBaseUrlError(ValueError):
    """Raised when a base URL fails validation."""


def validate_compatible_base_url(raw: str) -> str:
    """Validate and normalise a custom OpenAI-compatible base URL.

    Returns the normalised URL (scheme + host + optional path, no trailing /).
    Raises :class:`InvalidBaseUrlError` on failure.
    """
    if not raw or not isinstance(raw, str):
        raise InvalidBaseUrlError("base_url is required")
    raw = raw.strip()
    if not raw:
        raise InvalidBaseUrlError("base_url is empty")

    try:
        parts = urlsplit(raw)
    except ValueError as exc:
        raise InvalidBaseUrlError("base_url is malformed") from exc

    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise InvalidBaseUrlError("base_url scheme must be 'http' or 'https'")

    if not parts.netloc:
        raise InvalidBaseUrlError("base_url is missing a host")

    if parts.username or parts.password:
        raise InvalidBaseUrlError(
            "base_url must not embed credentials — provide a bearer separately"
        )

    if parts.query or parts.fragment:
        raise InvalidBaseUrlError("base_url must not include a query string or fragment")

    hostname = (parts.hostname or "").lower()
    if not hostname:
        raise InvalidBaseUrlError("base_url has an empty hostname")

    if scheme == "http":
        if hostname == "localhost":
            pass
        else:
            try:
                addr = ipaddress.ip_address(hostname)
            except ValueError as exc:
                raise InvalidBaseUrlError(
                    "http:// base_url must be loopback or a private (RFC1918) IP"
                ) from exc
            if not any(addr in net for net in _PRIVATE_NETWORKS):
                raise InvalidBaseUrlError(
                    "http:// base_url must be loopback or a private (RFC1918) IP"
                )

    # Preserve path but drop trailing slash for stable storage. Empty path is OK.
    path = (parts.path or "").rstrip("/")

    # Rebuild without credentials / query / fragment.
    # Use the netloc minus any user-info (urlsplit accepts these in raw form;
    # we've already rejected those above, so netloc is host[:port]).
    netloc = parts.netloc
    if "@" in netloc:
        netloc = netloc.rsplit("@", 1)[-1]

    normalised = urlunsplit((scheme, netloc, path, "", ""))
    return normalised
