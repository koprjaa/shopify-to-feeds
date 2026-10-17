// Project: shopify-to-feeds
// File: tests/feeds.rs
// Description: Empty guards, Python-derived XML fixtures and complete mock runs.
// Author: Jan Alexandr Kopřiva
// License: MIT

use serde_json::{json, Value};
use shopify_to_feeds::{
    client::{ShopifyClient, Transport},
    feeds::*,
    Result,
};
use std::sync::Mutex;
const STORE: &str = "https://shop.myshopify.com";
const KINDS: [FeedType; 3] = [FeedType::Google, FeedType::Bing, FeedType::Zbozi];
struct Fixture {
    empty: bool,
    calls: Mutex<Vec<String>>,
}
impl Transport for Fixture {
    fn get(&self, url: &str, _: &str) -> Result<Value> {
        self.calls.lock().unwrap().push(url.into());
        if self.empty {
            return Ok(json!({}));
        }
        let url = reqwest::Url::parse(url)?;
        if url.path() == "/collections.json" {
            return Ok(if url.query() == Some("page=1") {
                json!({"collections":[{"title":"All","handle":"all"}]})
            } else {
                json!({"collections":[]})
            });
        }
        if url.query() == Some("limit=1") || url.query().unwrap_or("").starts_with("page=1") {
            return Ok(json!({"products":[product()]}));
        }
        Ok(json!({"products":[]}))
    }
}
fn product() -> Value {
    serde_json::from_str(include_str!("fixtures/product.json")).unwrap()
}
fn fixture(empty: bool) -> Fixture {
    Fixture {
        empty,
        calls: Mutex::new(vec![]),
    }
}
#[test]
fn no_products_is_an_error() {
    assert!(require_products(STORE, &[]).is_err());
}
#[test]
fn the_error_names_the_store() {
    assert!(require_products("https://shop.example.com", &[])
        .unwrap_err()
        .to_string()
        .contains("shop.example.com"));
}
#[test]
fn the_error_says_why_an_empty_feed_is_not_harmless() {
    assert!(require_products(STORE, &[])
        .unwrap_err()
        .to_string()
        .contains("delists"));
}
#[test]
fn one_product_is_enough_to_proceed() {
    require_products(STORE, &[Node::leaf("id", "1")]).unwrap();
}
#[test]
fn a_store_that_returned_nothing_writes_no_file() {
    for kind in KINDS {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("absent/feed.xml");
        let client = ShopifyClient::with_transport(STORE, fixture(true));
        assert!(generate(&client, kind, &path, "CZK", false, 4).is_err());
        assert!(!path.exists());
        assert!(!path.parent().unwrap().exists());
    }
}
#[test]
fn every_generator_checks_before_writing() {
    for kind in KINDS {
        assert!(render(kind, STORE, &json!({}), vec![]).is_err());
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("feed.xml");
        std::fs::write(&path, "old feed").unwrap();
        assert!(generate(
            &ShopifyClient::with_transport(STORE, fixture(true)),
            kind,
            &path,
            "CZK",
            false,
            4
        )
        .is_err());
        assert_eq!(std::fs::read_to_string(path).unwrap(), "old feed");
    }
}
#[test]
fn all_xml_bytes_match_python_derived_fixtures() {
    for (kind, expected) in [
        (
            FeedType::Google,
            include_bytes!("fixtures/google.xml").as_slice(),
        ),
        (
            FeedType::Bing,
            include_bytes!("fixtures/bing.xml").as_slice(),
        ),
        (
            FeedType::Zbozi,
            include_bytes!("fixtures/zbozi.xml").as_slice(),
        ),
    ] {
        let client = ShopifyClient::with_transport(STORE, fixture(false));
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("nested/feed.xml");
        generate(&client, kind, &path, "CZK", false, 4).unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), expected, "{}", kind.name());
        // Replacing an existing file is essential on Windows as well.
        generate(&client, kind, &path, "CZK", false, 4).unwrap();
        assert_eq!(std::fs::read(path).unwrap(), expected);
        let calls = client.transport.calls.lock().unwrap();
        assert!(calls.iter().any(|s| s.ends_with("/products.json?limit=1")));
        assert!(calls.iter().any(|s| s.ends_with(if kind == FeedType::Bing {
            "/products.json?page=2&limit=250"
        } else {
            "/collections/all/products.json?page=2"
        })));
    }
}
#[test]
fn corrected_google_namespace_occurs_once() {
    let items = process_product(FeedType::Google, STORE, "CZK", &product()).unwrap();
    let xml = render(FeedType::Google, STORE, &json!({}), items).unwrap();
    assert_eq!(xml.matches("xmlns:g=").count(), 1);
    assert!(xml.ends_with("</rss>"));
}
#[test]
fn corrected_zbozi_parameters_and_both_carriers_are_nested() {
    let items = process_product(FeedType::Zbozi, STORE, "CZK", &product()).unwrap();
    let xml = render(FeedType::Zbozi, STORE, &json!({}), items).unwrap();
    assert!(xml.contains("<PARAM><PARAM_NAME>Size</PARAM_NAME><VAL>Small</VAL></PARAM>"));
    assert_eq!(xml.matches("<DELIVERY_ID>ZASILKOVNA").count(), 2);
    assert_eq!(xml.matches("<DELIVERY_ID>PPL").count(), 2);
}
#[test]
fn google_uses_singular_image_and_empty_tags_list() {
    let mut p = product();
    p["images"] = json!([]);
    p["image"] = json!({"src":"https://cdn.shopify.com/single.jpg"});
    p["tags"] = json!([]);
    let nodes = process_product(FeedType::Google, STORE, "EUR", &p).unwrap();
    let xml = render(FeedType::Google, STORE, &json!({}), nodes).unwrap();
    assert!(xml.contains("<g:google_product_category />"));
    assert!(xml.contains("<g:price>19.99 EUR"));
    assert!(xml.contains("<g:image_link>https://cdn.shopify.com/single.jpg"));
}
#[test]
fn malformed_google_variant_is_skipped_but_bing_aborts() {
    let mut p = product();
    p["variants"][0]["price"] = json!("broken");
    let nodes = process_product(FeedType::Google, STORE, "CZK", &p).unwrap();
    assert_eq!(nodes.len(), 2);
    assert_eq!(
        nodes[0]
            .children
            .iter()
            .find(|n| n.name == "g:price")
            .unwrap()
            .text,
        "0.00 CZK"
    );
    assert!(process_product(FeedType::Bing, STORE, "CZK", &p).is_err());
    p["tags"] = json!([123]);
    assert!(process_product(FeedType::Google, STORE, "CZK", &p)
        .unwrap()
        .is_empty());
}
#[test]
fn zbozi_string_tags_keep_original_character_join() {
    let mut p = product();
    p["tags"] = json!("ab");
    let nodes = process_product(FeedType::Zbozi, STORE, "CZK", &p).unwrap();
    assert_eq!(
        nodes[0]
            .children
            .iter()
            .find(|n| n.name == "CUSTOM_LABEL_2")
            .unwrap()
            .text,
        "a | b"
    );
}
#[test]
fn normalization_keeps_store_paths_but_product_links_are_absolute() {
    assert_eq!(
        shopify_to_feeds::client::normalize("shop.myshopify.com/path///"),
        "https://shop.myshopify.com/path"
    );
    let nodes = process_product(
        FeedType::Bing,
        "https://shop.myshopify.com/path",
        "CZK",
        &product(),
    )
    .unwrap();
    assert_eq!(
        nodes[0]
            .children
            .iter()
            .find(|n| n.name == "Link")
            .unwrap()
            .text,
        "https://shop.myshopify.com/products/plant-pot-extra?variant=101"
    );
}

#[test]
fn negative_fractional_integer_price_has_no_negative_zero() {
    let mut p = product();
    p["variants"][0]["price"] = json!("-0.25");
    let nodes = process_product(FeedType::Bing, STORE, "CZK", &p).unwrap();
    assert_eq!(
        nodes[0]
            .children
            .iter()
            .find(|n| n.name == "Price")
            .unwrap()
            .text,
        "0 CZK"
    );
}

#[test]
fn unicode_product_links_preserve_original_urljoin_text() {
    let mut p = product();
    p["handle"] = json!("žluťoučký");
    let nodes = process_product(
        FeedType::Google,
        "https://SHOP.myshopify.com:443/subpath",
        "CZK",
        &p,
    )
    .unwrap();
    assert_eq!(
        nodes[0]
            .children
            .iter()
            .find(|n| n.name == "g:link")
            .unwrap()
            .text,
        "https://SHOP.myshopify.com:443/products/žluťoučký"
    );
}
#[test]
fn public_generators_preserve_library_defaults_and_empty_error_type() {
    use shopify_to_feeds::{BingFeedGenerator, GoogleFeedGenerator, ZboziFeedGenerator};
    let g = GoogleFeedGenerator::new("shop.myshopify.com/");
    assert_eq!(g.currency, "CZK");
    assert!(!g.download_images);
    assert_eq!(g.max_workers, 4);
    assert_eq!(g.get_feed_type(), "google");
    assert_eq!(g.client.store_url, STORE);
    let b = BingFeedGenerator::new(STORE);
    assert_eq!(b.currency, "CZK");
    assert_eq!(b.get_feed_type(), "bing");
    assert_eq!(ZboziFeedGenerator::new(STORE).get_feed_type(), "zbozi");
    assert!(require_products(STORE, &[])
        .unwrap_err()
        .downcast_ref::<EmptyFeedError>()
        .is_some());
}

#[cfg(unix)]
#[test]
fn atomic_replacement_preserves_permissions_and_does_not_follow_symlinks() {
    use std::os::unix::fs::{symlink, PermissionsExt};
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("feed.xml");
    std::fs::write(&path, "old").unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o640)).unwrap();
    publish(&path, b"new").unwrap();
    assert_eq!(
        std::fs::metadata(&path).unwrap().permissions().mode() & 0o777,
        0o640
    );
    let outside = root.path().join("outside.xml");
    std::fs::write(&outside, "unchanged").unwrap();
    std::fs::remove_file(&path).unwrap();
    symlink(&outside, &path).unwrap();
    publish(&path, b"replacement").unwrap();
    assert_eq!(std::fs::read_to_string(outside).unwrap(), "unchanged");
    assert_eq!(std::fs::read_to_string(path).unwrap(), "replacement");
}
