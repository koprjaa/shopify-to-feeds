"""
Base class for feed generators.
"""

import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin


logger = logging.getLogger(__name__)


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

