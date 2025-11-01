"""
Shopify API client for fetching products and collections.
"""

import time
import logging
import requests
from typing import List, Dict, Any, Optional, Generator
from urllib.parse import urljoin


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
        retry_delay: int = 180,
        user_agent: Optional[str] = None
    ):
        """
        Initialize Shopify client.

        Args:
            store_url: Base URL of the Shopify store
            max_retries: Maximum number of retries for failed requests
            retry_delay: Delay between retries in seconds
            user_agent: Custom user agent string
        """
        self.store_url = store_url.rstrip('/')
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.user_agent = user_agent or self.DEFAULT_USER_AGENT
        self.logger = logging.getLogger(self.__class__.__name__)

    def _make_request(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Make HTTP GET request with retry logic.

        Args:
            url: URL to request

        Returns:
            JSON response data or None if request failed
        """
        headers = {"User-Agent": self.user_agent}

        for attempt in range(self.max_retries):
            try:
                self.logger.debug(
                    f"Making request to {url} (Attempt {attempt + 1}/{self.max_retries})"
                )
                response = requests.get(url, headers=headers, timeout=30)
                response.raise_for_status()
                self.logger.debug(f"Request successful: {response.status_code}")
                return response.json()
            except requests.RequestException as e:
                self.logger.warning(
                    f"Request failed (attempt {attempt + 1}/{self.max_retries}): {str(e)}"
                )
                if attempt < self.max_retries - 1:
                    self.logger.info(f"Retrying in {self.retry_delay} seconds...")
                    time.sleep(self.retry_delay)

        self.logger.error(
            f"Failed to retrieve data from {url} after {self.max_retries} attempts"
        )
        return None

    def get_collections(self) -> Generator[Dict[str, Any], None, None]:
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

    def get_collection_products(self, collection_handle: str) -> Generator[Dict[str, Any], None, None]:
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

            for product in products:
                yield product

            page += 1

    def get_all_products(self) -> Generator[Dict[str, Any], None, None]:
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

            for product in products:
                yield product

            page += 1

    def get_shop_info(self) -> Optional[Dict[str, str]]:
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
        except Exception as e:
            self.logger.error(f"Error fetching shop info: {str(e)}")
            return None

