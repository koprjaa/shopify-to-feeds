#
# Project: shopify-to-feeds
# File:    test_security.py
#
# Description:
# Tests for the API-key auth and the SSRF guard on user-supplied URLs.
#
# Author:
# Jan Alexandr Kopřiva
# jan.alexandr.kopriva@gmail.com
#
# License: MIT
#

"""Tests for the API-key auth and the SSRF guard on user-supplied URLs.

The feed endpoints are reachable from the internet and both the store URL and
the image URLs are supplied by the caller, so a gap here turns the service into
a proxy for whatever the caller wants fetched. These pin down the parts that
are easy to weaken by accident: the allowlist anchoring, the private-address
rejection, and the fail-closed behaviour when no API key is configured.
"""

import asyncio
import socket

import pytest
from fastapi import HTTPException

from shopify_to_feeds.security import (
    UrlValidationError,
    require_feed_api_key,
    validate_image_url,
    validate_store_url,
)


@pytest.fixture(autouse=True)
def offline_resolver(monkeypatch):
    """Resolve names without touching DNS.

    These tests pin down the allowlist and the address-range rules, not the
    state of the network, so a real lookup would only make them slow and make
    them fail wherever a domain is unreachable. Every hostname resolves to one
    public address; literal IPs never reach the resolver.
    """

    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


# --- API key auth -----------------------------------------------------------


def test_missing_configuration_fails_closed(monkeypatch):
    """An unset FEED_API_KEY must return 503, never an open endpoint."""
    monkeypatch.delenv("FEED_API_KEY", raising=False)
    with pytest.raises(HTTPException) as excinfo:
        _run(require_feed_api_key(x_api_key="anything"))
    assert excinfo.value.status_code == 503


def test_wrong_key_is_rejected(monkeypatch):
    monkeypatch.setenv("FEED_API_KEY", "correct-secret")
    with pytest.raises(HTTPException) as excinfo:
        _run(require_feed_api_key(x_api_key="wrong-secret"))
    assert excinfo.value.status_code == 401


def test_absent_header_is_rejected(monkeypatch):
    monkeypatch.setenv("FEED_API_KEY", "correct-secret")
    with pytest.raises(HTTPException) as excinfo:
        _run(require_feed_api_key(x_api_key=None))
    assert excinfo.value.status_code == 401


def test_correct_key_passes(monkeypatch):
    monkeypatch.setenv("FEED_API_KEY", "correct-secret")
    assert _run(require_feed_api_key(x_api_key="correct-secret")) is None


def _run(coro):
    """Drive a coroutine to completion without pulling in an async test plugin."""
    return asyncio.run(coro)


# --- store URL allowlist ----------------------------------------------------


def test_a_shopify_store_is_accepted():
    assert validate_store_url("https://listnato.myshopify.com") == "https://listnato.myshopify.com"


def test_a_bare_host_gets_https():
    assert validate_store_url("listnato.myshopify.com") == "https://listnato.myshopify.com"


def test_an_unlisted_host_is_rejected():
    with pytest.raises(UrlValidationError):
        validate_store_url("https://example.com")


def test_a_lookalike_host_does_not_match_the_suffix():
    """`evil-myshopify.com` must not pass as a `.myshopify.com` host."""
    with pytest.raises(UrlValidationError):
        validate_store_url("https://evil-myshopify.com")


def test_a_configured_host_is_accepted(monkeypatch):
    monkeypatch.setenv("FEED_ALLOWED_HOSTS", "listnato.cz")
    assert validate_store_url("https://listnato.cz") == "https://listnato.cz"


def test_a_configured_host_does_not_admit_a_lookalike(monkeypatch):
    monkeypatch.setenv("FEED_ALLOWED_HOSTS", "listnato.cz")
    with pytest.raises(UrlValidationError):
        validate_store_url("https://notlistnato.cz")


def test_plain_http_is_rejected():
    with pytest.raises(UrlValidationError):
        validate_store_url("http://listnato.myshopify.com")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://x", "ftp://x.myshopify.com"])
def test_a_non_http_scheme_is_rejected(url):
    with pytest.raises(UrlValidationError):
        validate_store_url(url)


# --- SSRF: address ranges ---------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",        # loopback
        "169.254.169.254",  # cloud metadata
        "10.0.0.1",         # RFC1918
        "192.168.1.1",      # RFC1918
        "172.16.0.1",       # RFC1918
        "0.0.0.0",          # unspecified
        "[::1]",            # IPv6 loopback
    ],
)
def test_a_private_address_is_rejected_even_when_allowlisted(host, monkeypatch):
    """The allowlist must not be a way to reach the internal network."""
    bare = host.strip("[]")
    monkeypatch.setenv("FEED_ALLOWED_HOSTS", bare)
    with pytest.raises(UrlValidationError):
        validate_store_url(f"https://{host}")


def test_an_image_on_the_shopify_cdn_is_accepted():
    url = "https://cdn.shopify.com/s/files/1/0/0/products/boot.jpg"
    assert validate_image_url(url) == url


def test_an_image_from_an_unlisted_host_is_rejected():
    with pytest.raises(UrlValidationError):
        validate_image_url("https://example.com/boot.jpg")


def test_an_image_on_a_private_address_is_rejected(monkeypatch):
    monkeypatch.setenv("FEED_ALLOWED_HOSTS", "169.254.169.254")
    with pytest.raises(UrlValidationError):
        validate_image_url("http://169.254.169.254/latest/meta-data/")


@pytest.mark.parametrize("url", ["", None, 123])
def test_an_empty_or_non_string_url_is_rejected(url):
    with pytest.raises(UrlValidationError):
        validate_store_url(url)


# --- feed file serving ------------------------------------------------------


def test_a_traversing_filename_is_refused(tmp_path, monkeypatch):
    """`filename` arrives from the URL, so it must not walk out of STATIC_DIR."""
    from shopify_to_feeds import api

    monkeypatch.setattr(api, "STATIC_DIR", str(tmp_path / "feeds"))
    (tmp_path / "feeds").mkdir()
    (tmp_path / "secret.txt").write_text("not yours")

    for attempt in ["../secret.txt", "../../etc/passwd", "..", "", "sub/dir.xml", "a\\b.xml"]:
        with pytest.raises(HTTPException) as excinfo:
            api.resolve_feed_file(attempt)
        assert excinfo.value.status_code == 404


def test_a_real_feed_file_is_served(tmp_path, monkeypatch):
    from shopify_to_feeds import api

    feeds = tmp_path / "feeds"
    feeds.mkdir()
    (feeds / "abc12345_google.xml").write_text("<rss/>")
    monkeypatch.setattr(api, "STATIC_DIR", str(feeds))

    assert api.resolve_feed_file("abc12345_google.xml").name == "abc12345_google.xml"


def test_a_missing_feed_file_is_a_404(tmp_path, monkeypatch):
    from shopify_to_feeds import api

    feeds = tmp_path / "feeds"
    feeds.mkdir()
    monkeypatch.setattr(api, "STATIC_DIR", str(feeds))

    with pytest.raises(HTTPException) as excinfo:
        api.resolve_feed_file("nope.xml")
    assert excinfo.value.status_code == 404
