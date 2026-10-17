// Project: shopify-to-feeds
// File: tests/helpers.rs
// Description: Equivalent coverage of every original helper test.
// Author: Jan Alexandr Kopřiva
// License: MIT

use serde_json::json;
use shopify_to_feeds::helpers::*;
#[test]
fn markup_is_stripped_from_a_description() {
    assert_eq!(
        remove_html_tags(&json!("<p>Lehké boty <strong>na běh</strong>.</p>"), None),
        "Lehké boty na běh."
    );
}
#[test]
fn whitespace_is_collapsed() {
    assert_eq!(
        remove_html_tags(&json!("<p>Text\n\n  s   mezerami</p>"), None),
        "Text s mezerami"
    );
}
#[test]
fn an_empty_description_gives_an_empty_string() {
    for v in [json!(""), json!(null), json!("<p></p>")] {
        assert_eq!(remove_html_tags(&v, None), "");
    }
}
#[test]
fn a_description_is_truncated_to_the_limit() {
    assert_eq!(
        remove_html_tags(&json!("x".repeat(200)), Some(50)),
        "x".repeat(50)
    );
}
#[test]
fn a_description_under_the_limit_is_untouched() {
    assert_eq!(
        remove_html_tags(&json!("krátký popis"), Some(50)),
        "krátký popis"
    );
}
#[test]
fn no_limit_leaves_a_long_description_whole() {
    assert_eq!(remove_html_tags(&json!("x".repeat(200)), None).len(), 200);
}
#[test]
fn a_description_that_is_not_a_string_is_coerced() {
    assert_eq!(remove_html_tags(&json!(1234), None), "1234");
}
#[test]
fn czech_characters_survive() {
    assert_eq!(
        remove_html_tags(&json!("<p>Příliš žluťoučký kůň</p>"), None),
        "Příliš žluťoučký kůň"
    );
}
#[test]
fn a_price_always_carries_two_decimals_and_a_currency() {
    for (p, e) in [
        (json!("1990.00"), "1990.00 CZK"),
        (json!("1990"), "1990.00 CZK"),
        (json!("0"), "0.00 CZK"),
        (json!("19.9"), "19.90 CZK"),
        (json!(1990.5), "1990.50 CZK"),
    ] {
        assert_eq!(format_price(&p, "CZK"), e);
    }
}
#[test]
fn the_currency_can_be_changed() {
    assert_eq!(format_price(&json!("10"), "EUR"), "10.00 EUR");
}
#[test]
fn a_price_that_is_not_a_number_falls_back_to_zero() {
    for v in [
        json!(""),
        json!(null),
        json!("zdarma"),
        json!([]),
        json!({}),
    ] {
        assert_eq!(format_price(&v, "CZK"), "0.00 CZK");
    }
}
#[test]
fn a_price_is_rounded_rather_than_truncated() {
    assert_eq!(format_price(&json!("19.999"), "CZK"), "20.00 CZK");
}
#[test]
fn grams_convert_to_kilograms_by_default() {
    assert_eq!(
        format_weight(&json!(1500), "kg").unwrap().as_deref(),
        Some("1.500 kg")
    );
}
#[test]
fn a_light_item_keeps_three_decimals() {
    assert_eq!(
        format_weight(&json!(350), "kg").unwrap().as_deref(),
        Some("0.350 kg")
    );
}
#[test]
fn the_unit_can_be_left_as_grams() {
    assert_eq!(
        format_weight(&json!(350), "g").unwrap().as_deref(),
        Some("350.0 g")
    );
}
#[test]
fn a_missing_weight_gives_none() {
    for v in [json!(null), json!(0)] {
        assert_eq!(format_weight(&v, "kg").unwrap(), None);
    }
}
#[test]
fn a_weight_given_as_a_string_is_accepted() {
    assert_eq!(
        format_weight(&json!("1500"), "kg").unwrap().as_deref(),
        Some("1.500 kg")
    );
}
#[test]
fn unicode_truncation_and_entities_match_original() {
    assert_eq!(
        remove_html_tags(&json!("<p>kůň &amp; <> text</p>"), Some(5)),
        "kůň &"
    );
    assert_eq!(remove_html_tags(&json!("<>"), Some(0)), "<>");
}

#[test]
fn python_control_whitespace_is_collapsed() {
    assert_eq!(
        remove_html_tags(&json!("a\u{1c}\u{1d}\u{1e}\u{1f}b"), None),
        "a b"
    );
}

#[test]
fn negative_description_limit_uses_python_slice_semantics() {
    assert_eq!(remove_html_tags(&json!("kůň"), Some(-1)), "ků");
    assert_eq!(remove_html_tags(&json!("text"), Some(-100)), "");
}
