#
# Project: shopify-to-feeds
# File:    base.py
#
# Description:
# Shared base for the feed generators: output paths and the XML writing step.
#
# Author:
# Jan Alexandr Kopřiva
# jan.alexandr.kopriva@gmail.com
#
# License: MIT
#

"""
Base class for feed generators.
"""

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class EmptyFeedError(RuntimeError):
    """No products were collected, so there is nothing to publish."""


class BaseFeedGenerator(ABC):
    """
    Base class for all feed generators.

    This class provides common functionality for fetching products from Shopify
    stores and generating XML feeds.
    """

    def __init__(self, store_url: str):
        """
        Initialize the feed generator.

        Args:
            store_url: The URL of the Shopify store
        """
        self.store_url = self._validate_url(store_url)
        self.logger = logging.getLogger(self.__class__.__name__)

    @staticmethod
    def _validate_url(url: str) -> str:
        """
        Validate and normalize store URL.

        Args:
            url: The store URL to validate

        Returns:
            Normalized URL with protocol
        """
        if not url.startswith(('http://', 'https://')):
            url = f'https://{url}'
        return url.rstrip('/')

    def _require_products(self, variants: list) -> None:
        """Refuse to write a feed with nothing in it.

        A merchant centre reads a feed as the whole catalogue. An empty one is
        not a harmless no-op, it delists every product the store has. When every
        request to the store failed, the generators still wrote a valid empty
        channel and reported success, which is the worst possible outcome: a
        file that looks fine and wipes the listing.
        """
        if not variants:
            raise EmptyFeedError(
                f"No products collected from {self.store_url}. Refusing to write an "
                f"empty feed, because uploading one delists the whole catalogue."
            )

    @abstractmethod
    def generate(self, output_path: str, **kwargs) -> str:
        """
        Generate the feed file.

        Args:
            output_path: Path where the feed file should be saved
            **kwargs: Additional feed-specific parameters

        Returns:
            Path to the generated feed file
        """
        pass

    @abstractmethod
    def get_feed_type(self) -> str:
        """
        Get the feed type identifier.

        Returns:
            Feed type name (e.g., 'google', 'bing', 'zbozi')
        """
        pass

