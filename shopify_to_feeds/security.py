#
# Project: shopify-to-feeds
# File:    security.py
#
# Description:
# API-key auth and SSRF-safe URL validation for the publicly deployed endpoints.
#
# Author:
# Jan Alexandr Kopřiva
# jan.alexandr.kopriva@gmail.com
#
# License: MIT
#

"""
Security helpers: API-key auth and SSRF-safe URL validation.

These guard the publicly deployed feed endpoints (listnato.cz) against:
  - unauthenticated abuse of the feed-update endpoints
  - server-side request forgery (SSRF) via user-controlled store/image URLs
"""

import hmac
import ipaddress
import logging
import os
import socket
from urllib.parse import urlparse

from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)


# --- API key auth ----------------------------------------------------------

FEED_API_KEY_ENV = "FEED_API_KEY"


async def require_feed_api_key(
    x_api_key: str | None = Header(default=None),
) -> None:
    """
    FastAPI dependency enforcing an API key on feed endpoints.

    The expected key is read from the FEED_API_KEY environment variable.
    Fails closed: if the env var is unset/empty the endpoint returns 503,
    so a misconfigured deployment can never expose the endpoint unguarded.
    """
    expected = os.environ.get(FEED_API_KEY_ENV, "").strip()
    if not expected:
        logger.error(
            "%s is not configured; refusing feed request (fail-closed).",
            FEED_API_KEY_ENV,
        )
        raise HTTPException(
            status_code=503,
            detail="Feed API is not configured.",
        )

    if not x_api_key or not _constant_time_eq(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


def _constant_time_eq(a: str, b: str) -> bool:
    """Constant-time string comparison to avoid timing side channels."""
    return hmac.compare_digest(a, b)


# --- SSRF-safe URL validation ----------------------------------------------

class UrlValidationError(ValueError):
    """Raised when a URL fails SSRF/scheme validation."""


def _allowed_host_suffixes() -> tuple:
    """
    Host suffixes that are always permitted (in addition to *.myshopify.com).

    Configured via FEED_ALLOWED_HOSTS as a comma-separated list of host
    suffixes, e.g. "example.com,cdn.shopify.com". Matching is suffix-based
    and dot-anchored so "evil-example.com" does NOT match "example.com".
    """
    raw = os.environ.get("FEED_ALLOWED_HOSTS", "")
    suffixes = [h.strip().lower().lstrip(".") for h in raw.split(",") if h.strip()]
    return tuple(suffixes)


# Shopify product image CDN host(s). Always allowed for image downloads.
_SHOPIFY_CDN_SUFFIXES = ("cdn.shopify.com", "shopify.com", "shopifycdn.com")


def _host_is_allowlisted(host: str, *, allow_shopify_cdn: bool = False) -> bool:
    host = host.lower().rstrip(".")
    if host.endswith(".myshopify.com") or host == "myshopify.com":
        return True
    for suffix in _allowed_host_suffixes():
        if host == suffix or host.endswith("." + suffix):
            return True
    if allow_shopify_cdn:
        for suffix in _SHOPIFY_CDN_SUFFIXES:
            if host == suffix or host.endswith("." + suffix):
                return True
    return False


def _ip_is_forbidden(ip: ipaddress._BaseAddress) -> bool:
    """Reject private/loopback/link-local/reserved/multicast/unspecified IPs."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None
            and _ip_is_forbidden(ip.ipv4_mapped))
    )


def _resolve_and_check_ips(host: str) -> None:
    """
    Resolve a hostname and reject if ANY resolved address is in a
    private/loopback/link-local/reserved range. Raises UrlValidationError.
    """
    # A literal IP host must also be checked directly. The parse is kept in its
    # own try: UrlValidationError subclasses ValueError, so raising it inside a
    # block guarded by `except ValueError` would swallow the rejection and let
    # every literal address through.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None  # not a literal IP, resolve it via DNS below

    if literal is not None:
        if _ip_is_forbidden(literal):
            raise UrlValidationError(f"Disallowed IP address: {host}")
        return

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise UrlValidationError(f"Could not resolve host: {host}") from e

    if not infos:
        raise UrlValidationError(f"Could not resolve host: {host}")

    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as e:
            raise UrlValidationError(f"Unparseable resolved address: {ip_str}") from e
        if _ip_is_forbidden(ip):
            raise UrlValidationError(
                f"Host {host} resolves to a disallowed address: {ip_str}"
            )


def validate_store_url(url: str, *, require_https: bool = True) -> str:
    """
    Validate a user-supplied Shopify store URL before any server-side fetch.

    - Requires an http(s) scheme (https by default).
    - Requires the host to be allowlisted (*.myshopify.com or FEED_ALLOWED_HOSTS).
    - Resolves the host and rejects private/loopback/link-local/reserved IPs.

    Returns the normalized URL (scheme + host, trailing slash stripped).
    Raises UrlValidationError on any violation.
    """
    if not url or not isinstance(url, str):
        raise UrlValidationError("Empty store URL.")

    # Normalize: add https:// if no scheme present.
    if "://" not in url:
        url = "https://" + url

    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()

    allowed_schemes = ("https",) if require_https else ("http", "https")
    if scheme not in allowed_schemes:
        raise UrlValidationError(f"Disallowed URL scheme: {scheme!r}")

    host = parsed.hostname
    if not host:
        raise UrlValidationError("URL has no host.")

    if not _host_is_allowlisted(host):
        raise UrlValidationError(f"Host not allowlisted: {host}")

    _resolve_and_check_ips(host)

    return url.rstrip("/")


def validate_image_url(url: str) -> str:
    """
    Validate an image URL before downloading it server-side.

    - Requires http(s) scheme (http allowed: some legacy Shopify CDN links).
    - Allows Shopify CDN hosts in addition to the store allowlist.
    - Resolves host and rejects private/loopback/link-local/reserved IPs.

    Returns the URL unchanged on success; raises UrlValidationError otherwise.
    """
    if not url or not isinstance(url, str):
        raise UrlValidationError("Empty image URL.")

    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise UrlValidationError(f"Disallowed image URL scheme: {scheme!r}")

    host = parsed.hostname
    if not host:
        raise UrlValidationError("Image URL has no host.")

    if not _host_is_allowlisted(host, allow_shopify_cdn=True):
        raise UrlValidationError(f"Image host not allowlisted: {host}")

    _resolve_and_check_ips(host)

    return url
