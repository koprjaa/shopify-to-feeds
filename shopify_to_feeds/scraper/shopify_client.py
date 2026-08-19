#
# Project: shopify-to-feeds
# File:    shopify_client.py
#
# Description:
# Reads products and collections from a Shopify store over its public JSON endpoints.
#
# Author:
# Jan Alexandr Kopřiva
# jan.alexandr.kopriva@gmail.com
#
# License: MIT
#

"""
Shopify API client for fetching products and collections.
"""

import logging
import time
from collections.abc import Generator
from typing import Any
from urllib.parse import urljoin

import requests

from shopify_to_feeds.security import UrlValidationError, validate_store_url

logger = logging.getLogger(__name__)


class ShopifyClient:
    """
    Client for fetching data from Shopify stores via their public JSON API.
    """

    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36"
    )

    def __init__(
        self,
        store_url: str,
        max_retries: int = 3,
        retry_delay: int = 5,
        user_agent: str | None = None
    ):
        """
        Initialize Shopify client.

        Args:
            store_url: Base URL of the Shopify store
            max_retries: Maximum number of retries for failed requests
            retry_delay: Seconds before the first retry. Doubles on each further attempt.
            user_agent: Custom user agent string
        """
        self.store_url = store_url.rstrip('/')
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.user_agent = user_agent or self.DEFAULT_USER_AGENT
        self.logger = logging.getLogger(self.__class__.__name__)

    def _make_request(self, url: str) -> dict[str, Any] | None:
        """
        Make HTTP GET request with retry logic.

        Args:
            url: URL to request

        Returns:
            JSON response data or None if request failed
        """
        # SSRF guard (defense in depth): the store URL reaches here from the
        # API layer, so validate every request URL before it is fetched.
        try:
            validate_store_url(url)
        except UrlValidationError as e:
            self.logger.warning("Rejected request URL %r: %s", url, e)
            return None

        headers = {"User-Agent": self.user_agent}

        for attempt in range(self.max_retries):
            try:
                self.logger.debug(
                    f"Making request to {url} (Attempt {attempt + 1}/{self.max_retries})"
                )
                response = requests.get(url, headers=headers, timeout=30, allow_redirects=False)
                response.raise_for_status()
                self.logger.debug(f"Request successful: {response.status_code}")
                return response.json()
            except requests.RequestException as e:
                self.logger.warning(
                    f"Request failed (attempt {attempt + 1}/{self.max_retries}): {e!s}"
                )
                if attempt < self.max_retries - 1:
                    # Back off rather than waiting the same long delay each time.
                    # A flat 180 seconds meant three attempts against a dead store
                    # took nine minutes and looked like a hang.
                    delay = self.retry_delay * (2**attempt)
                    self.logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)

        self.logger.error(
            f"Failed to retrieve data from {url} after {self.max_retries} attempts"
        )
        return None

    def get_collections(self) -> Generator[dict[str, Any], None, None]:
        """
        Fetch all collections from the store.

        Yields:
            Collection dictionaries
        """
        page = 1
        total_collections = 0

        while True:
            url = urljoin(self.store_url, f"/collections.json?page={page}")
            self.logger.info(f"Fetching collections (page {page})")

            data = self._make_request(url)
            if not data or not data.get("collections"):
                break

            collections = data["collections"]
            total_collections += len(collections)
            self.logger.info(f"Found {len(collections)} collections on page {page}")

            for collection in collections:
                self.logger.info(
                    f"Processing collection: {collection['title']} ({collection['handle']})"
                )
                yield collection

            page += 1

        self.logger.info(f"Total collections found: {total_collections}")

    def get_collection_products(self, collection_handle: str) -> Generator[dict[str, Any], None, None]:
        """
        Fetch all products from a specific collection.

        Args:
            collection_handle: Handle of the collection

        Yields:
            Product dictionaries
        """
        page = 1

        while True:
            url = urljoin(
                self.store_url,
                f"/collections/{collection_handle}/products.json?page={page}"
            )
            self.logger.info(
                f"Fetching products from collection: {collection_handle} (page {page})"
            )

            data = self._make_request(url)
            if not data or not data.get("products"):
                break

            products = data["products"]
            self.logger.info(f"Found {len(products)} products on page {page}")

            yield from products

            page += 1

    def get_all_products(self) -> Generator[dict[str, Any], None, None]:
        """
        Fetch all products from the store.

        Yields:
            Product dictionaries
        """
        page = 1

        while True:
            url = urljoin(self.store_url, f"/products.json?page={page}&limit=250")
            self.logger.info(f"Fetching all products (page {page})")

            data = self._make_request(url)
            if not data or not data.get("products"):
                break

            products = data["products"]
            self.logger.info(f"Found {len(products)} products on page {page}")

            yield from products

            page += 1

    def get_shop_info(self) -> dict[str, str] | None:
        """
        Get basic shop information.

        Returns:
            Dictionary with shop info or None if failed
        """
        try:
            url = urljoin(self.store_url, "/products.json?limit=1")
            data = self._make_request(url)
            if data and data.get("products"):
                product = data["products"][0]
                return {
                    "name": product.get("vendor", ""),
                    "description": "",
                    "url": self.store_url
                }
            return None
        except Exception:
            self.logger.exception("Error fetching shop info")
            return None

