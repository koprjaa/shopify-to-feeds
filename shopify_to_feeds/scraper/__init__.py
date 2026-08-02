#
# Project: shopify-to-feeds
# File:    __init__.py
#
# Description:
# Exposes the Shopify client and the image downloader.
#
# Author:
# Jan Alexandr Kopřiva
# jan.alexandr.kopriva@gmail.com
#
# License: MIT
#

"""
Shopify scraper module for fetching products and collections.
"""

from shopify_to_feeds.scraper.image_downloader import ImageDownloader
from shopify_to_feeds.scraper.shopify_client import ShopifyClient

__all__ = [
    "ImageDownloader",
    "ShopifyClient",
]

