// Project: shopify-to-feeds
// File: tests/images.rs
// Description: Offline image download, deduplication and filename-race regressions.
// Author: Jan Alexandr Kopřiva
// Based on shopify-to-feeds by Jan Alexandr Kopřiva
// License: MIT

use shopify_to_feeds::{images::*, Result};
struct LocalImages;
impl ImageTransport for LocalImages {
    fn get(&self, url: &str) -> Result<Vec<u8>> {
        Ok(shopify_to_feeds::client::http_client_builder()
            .build()?
            .get(url)
            .header("User-Agent", IMAGE_USER_AGENT)
            .send()?
            .error_for_status()?
            .bytes()?
            .to_vec())
    }
}
#[test]
fn images_are_unique_and_basename_collisions_cannot_overwrite() {
    let server = httpmock::MockServer::start();
    let a = server.mock(|w, t| {
        w.path("/a/same.jpg").header("user-agent", IMAGE_USER_AGENT);
        t.body([0, 255, 13, 10, 65]);
    });
    let b = server.mock(|w, t| {
        w.path("/b/same.jpg");
        t.body([66, 0, 255]);
    });
    let urls = vec![
        server.url("/a/same.jpg"),
        server.url("/a/same.jpg"),
        server.url("/b/same.jpg"),
        String::new(),
    ];
    let root = tempfile::tempdir().unwrap();
    let result = download_product_images_with(&LocalImages, &urls, root.path(), 4).unwrap();
    assert_eq!(result.len(), 2);
    assert_ne!(result[&urls[0]], result[&urls[2]]);
    assert_eq!(
        std::fs::read(root.path().join(&result[&urls[0]])).unwrap(),
        [0, 255, 13, 10, 65]
    );
    assert_eq!(
        std::fs::read(root.path().join(&result[&urls[2]])).unwrap(),
        [66, 0, 255]
    );
    a.assert_calls(1);
    b.assert_calls(1);
}
#[test]
fn image_failures_are_not_retried_or_added_to_results() {
    let server = httpmock::MockServer::start();
    let m = server.mock(|w, t| {
        w.path("/missing.jpg");
        t.status(404);
    });
    let root = tempfile::tempdir().unwrap();
    assert!(download_product_images_with(
        &LocalImages,
        &[server.url("/missing.jpg")],
        root.path(),
        1
    )
    .unwrap()
    .is_empty());
    m.assert_calls(1);
}
#[test]
fn fallback_names_are_stable_and_safe() {
    assert_eq!(image_filename("https://cdn.shopify.com/a.jpg?q=1"), "a.jpg");
    let s = image_filename("https://cdn.shopify.com/");
    assert!(s.starts_with("image_"));
    assert_eq!(s, image_filename("https://cdn.shopify.com/"));
    assert!(!image_filename("https://cdn.shopify.com/a:b").contains(':'));
}
#[test]
fn empty_images_and_invalid_worker_counts_are_handled() {
    let root = tempfile::tempdir().unwrap();
    assert!(
        download_product_images_with(&LocalImages, &[], root.path(), 4)
            .unwrap()
            .is_empty()
    );
    assert!(download_product_images_with(&LocalImages, &[], root.path(), 0).is_err());
}
#[test]
fn production_image_guard_and_filename_guard_prevent_writes() {
    let root = tempfile::tempdir().unwrap();
    assert!(download_image("http://169.254.169.254/x", root.path(), "x").is_err());
    assert!(download_image_with(&LocalImages, "not fetched", root.path(), "../escape").is_err());
    assert_eq!(std::fs::read_dir(root.path()).unwrap().count(), 0);
}
