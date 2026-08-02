#
# Project: shopify-to-feeds
# File:    test_feed_generation.py
#
# Description:
# Tests that a run which collected nothing refuses to write a feed.
#
# Author:
# Jan Alexandr Kopřiva
# jan.alexandr.kopriva@gmail.com
#
# License: MIT
#

"""A merchant centre reads a feed as the whole catalogue.

When every request to the store failed, the generators still wrote a valid empty
channel and logged success. Uploading that file removes every product the store
has. An empty feed is not a harmless no-op, so it is now an error.
"""

import pytest

from shopify_to_feeds.feeds.base import BaseFeedGenerator, EmptyFeedError
from shopify_to_feeds.feeds.bing import BingFeedGenerator
from shopify_to_feeds.feeds.google import GoogleFeedGenerator
from shopify_to_feeds.feeds.zbozi import ZboziFeedGenerator

STORE = "https://shop.example.com"
GENERATORS = [GoogleFeedGenerator, BingFeedGenerator, ZboziFeedGenerator]


class Bare(BaseFeedGenerator):
    """The smallest concrete generator, so the guard can be tested on its own."""

    def generate(self, output_path: str, **kwargs) -> str:  # pragma: no cover - unused
        return output_path

    def get_feed_type(self) -> str:
        return "bare"


# --- the guard itself --------------------------------------------------------


def test_no_products_is_an_error():
    with pytest.raises(EmptyFeedError):
        Bare(STORE)._require_products([])


def test_the_error_names_the_store():
    with pytest.raises(EmptyFeedError, match=r"shop\.example\.com"):
        Bare(STORE)._require_products([])


def test_the_error_says_why_an_empty_feed_is_not_harmless():
    with pytest.raises(EmptyFeedError, match="delists"):
        Bare(STORE)._require_products([])


def test_one_product_is_enough_to_proceed():
    Bare(STORE)._require_products([{"id": 1}])


# --- every generator is guarded ----------------------------------------------


@pytest.mark.parametrize("generator", GENERATORS)
def test_a_store_that_returned_nothing_writes_no_file(generator, tmp_path, monkeypatch):
    out = tmp_path / "feed.xml"
    gen = generator(STORE)
    monkeypatch.setattr(gen.client, "get_collections", lambda *a, **k: iter([]))
    monkeypatch.setattr(gen.client, "get_all_products", lambda *a, **k: iter([]))
    monkeypatch.setattr(gen.client, "get_collection_products", lambda *a, **k: iter([]))

    with pytest.raises(EmptyFeedError):
        gen.generate(str(out))
    assert not out.exists(), "an empty feed must not reach the disk"


@pytest.mark.parametrize("generator", GENERATORS)
def test_every_generator_checks_before_writing(generator):
    """Pins the guard to the source, so a new generator cannot skip it."""
    import inspect

    source = inspect.getsource(generator.generate)
    assert "_require_products" in source
