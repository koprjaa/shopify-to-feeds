#
# Project: shopify-to-feeds
# File:    __init__.py
#
# Description:
# Exposes the Google, Bing, and Zbozi.cz feed generators.
#
# Author:
# Jan Alexandr Kopřiva
# jan.alexandr.kopriva@gmail.com
#
# License: MIT
#

"""
Feed generators for various e-commerce platforms.
"""

from shopify_to_feeds.feeds.bing import BingFeedGenerator
from shopify_to_feeds.feeds.google import GoogleFeedGenerator
from shopify_to_feeds.feeds.zbozi import ZboziFeedGenerator

__all__ = [
    "BingFeedGenerator",
    "GoogleFeedGenerator",
    "ZboziFeedGenerator",
]

