#
# Project: shopify-to-feeds
# File:    test_helpers.py
#
# Description:
# Tests for the value formatting every feed generator shares.
#
# Author:
# Jan Alexandr Kopřiva
# jan.alexandr.kopriva@gmail.com
#
# License: MIT
#

"""Tests for the value formatting every feed generator shares.

A wrong value here reaches Google Merchant Center, Bing and Zbozi.cz alike, and
a merchant centre rejects a feed rather than explaining it, so these are worth
pinning down.
"""

import pytest

from shopify_to_feeds.utils.helpers import format_price, format_weight, remove_html_tags

# --- remove_html_tags -------------------------------------------------------


def test_markup_is_stripped_from_a_description():
    assert remove_html_tags("<p>Lehké boty <strong>na běh</strong>.</p>") == "Lehké boty na běh."


def test_whitespace_is_collapsed():
    assert remove_html_tags("<p>Text\n\n  s   mezerami</p>") == "Text s mezerami"


@pytest.mark.parametrize("text", ["", None, "<p></p>"])
def test_an_empty_description_gives_an_empty_string(text):
    assert remove_html_tags(text) == ""


def test_a_description_is_truncated_to_the_limit():
    """Google caps a description, and an over-long one gets the item rejected."""
    assert remove_html_tags("x" * 200, max_length=50) == "x" * 50


def test_a_description_under_the_limit_is_untouched():
    assert remove_html_tags("krátký popis", max_length=50) == "krátký popis"


def test_no_limit_leaves_a_long_description_whole():
    assert len(remove_html_tags("x" * 200)) == 200


def test_a_description_that_is_not_a_string_is_coerced():
    assert remove_html_tags(1234) == "1234"


def test_czech_characters_survive():
    assert remove_html_tags("<p>Příliš žluťoučký kůň</p>") == "Příliš žluťoučký kůň"


# --- format_price -----------------------------------------------------------


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        ("1990.00", "1990.00 CZK"),
        ("1990", "1990.00 CZK"),
        ("0", "0.00 CZK"),
        ("19.9", "19.90 CZK"),
        (1990.5, "1990.50 CZK"),
    ],
)
def test_a_price_always_carries_two_decimals_and_a_currency(price, expected):
    assert format_price(price) == expected


def test_the_currency_can_be_changed():
    assert format_price("10", "EUR") == "10.00 EUR"


@pytest.mark.parametrize("price", ["", None, "zdarma", [], {}])
def test_a_price_that_is_not_a_number_falls_back_to_zero(price):
    """A merchant centre rejects an item with no price, so a value is always sent."""
    assert format_price(price) == "0.00 CZK"


def test_a_price_is_rounded_rather_than_truncated():
    assert format_price("19.999") == "20.00 CZK"


# --- format_weight ----------------------------------------------------------


def test_grams_convert_to_kilograms_by_default():
    assert format_weight(1500) == "1.500 kg"


def test_a_light_item_keeps_three_decimals():
    """350 g is 0.350 kg. Fewer decimals would round it to nothing."""
    assert format_weight(350) == "0.350 kg"


def test_the_unit_can_be_left_as_grams():
    assert format_weight(350, "g") == "350.0 g"


@pytest.mark.parametrize("grams", [None, 0])
def test_a_missing_weight_gives_none(grams):
    """Shipping is calculated from the weight, so a wrong one costs money."""
    assert format_weight(grams) is None


def test_a_weight_given_as_a_string_is_accepted():
    assert format_weight("1500") == "1.500 kg"
