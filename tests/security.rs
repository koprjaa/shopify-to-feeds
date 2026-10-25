// Project: shopify-to-feeds
// File: tests/security.rs
// Description: Offline equivalents of authentication, SSRF and file-serving tests.
// Author: Jan Alexandr Kopřiva
// License: AGPL-3.0-or-later
use shopify_to_feeds::security::*;
fn validate(s: &str, extra: &str, image: bool) -> shopify_to_feeds::Result<String> {
    validate_with(s, extra, image, true, |_, port| {
        Ok(vec![std::net::SocketAddr::from(([93, 184, 216, 34], port))])
    })
    .map(|v| v.0)
}
#[test]
fn missing_configuration_fails_closed() {
    for v in [None, Some(""), Some("  ")] {
        assert_eq!(authenticate(v, Some("anything")).unwrap_err().0, 503);
    }
}
#[test]
fn wrong_key_is_rejected() {
    assert_eq!(
        authenticate(Some("test-expected"), Some("test-other"))
            .unwrap_err()
            .0,
        401
    );
}
#[test]
fn absent_header_is_rejected() {
    assert_eq!(
        authenticate(Some("test-expected"), None).unwrap_err().0,
        401
    );
}
#[test]
fn correct_key_passes() {
    assert!(authenticate(Some("test-ž"), Some("test-ž")).is_ok());
    assert!(authenticate(Some("test-ž"), Some("test-š")).is_err());
    assert!(authenticate(Some(" test-expected "), Some("test-expected")).is_ok());
}
#[test]
fn a_shopify_store_is_accepted() {
    assert_eq!(
        validate("https://listnato.myshopify.com", "", false).unwrap(),
        "https://listnato.myshopify.com"
    );
}
#[test]
fn a_bare_host_gets_https() {
    assert_eq!(
        validate("listnato.myshopify.com", "", false).unwrap(),
        "https://listnato.myshopify.com"
    );
}
#[test]
fn an_unlisted_host_is_rejected() {
    assert!(validate("https://example.com", "", false).is_err());
}
#[test]
fn a_lookalike_host_does_not_match_the_suffix() {
    assert!(validate("https://evil-myshopify.com", "", false).is_err());
}
#[test]
fn a_configured_host_is_accepted() {
    assert!(validate("https://listnato.cz", "listnato.cz", false).is_ok());
}
#[test]
fn a_configured_host_does_not_admit_a_lookalike() {
    assert!(validate("https://notlistnato.cz", "listnato.cz", false).is_err());
}
#[test]
fn plain_http_is_rejected() {
    assert!(validate("http://listnato.myshopify.com", "", false).is_err());
}
#[test]
fn a_non_http_scheme_is_rejected() {
    for s in ["file:///etc/passwd", "gopher://x", "ftp://x.myshopify.com"] {
        assert!(validate(s, "", false).is_err());
    }
}
#[test]
fn a_private_address_is_rejected_even_when_allowlisted() {
    for h in [
        "127.0.0.1",
        "169.254.169.254",
        "10.0.0.1",
        "192.168.1.1",
        "172.16.0.1",
        "0.0.0.0",
        "[::1]",
    ] {
        assert!(
            validate(&format!("https://{h}"), h.trim_matches(['[', ']']), false).is_err(),
            "{h}"
        );
    }
}
#[test]
fn an_image_on_the_shopify_cdn_is_accepted() {
    let s = "https://cdn.shopify.com/s/files/1/0/0/products/boot.jpg";
    assert_eq!(validate(s, "", true).unwrap(), s);
}
#[test]
fn an_image_from_an_unlisted_host_is_rejected() {
    assert!(validate("https://example.com/boot.jpg", "", true).is_err());
}
#[test]
fn an_image_on_a_private_address_is_rejected() {
    assert!(validate(
        "http://169.254.169.254/latest/meta-data/",
        "169.254.169.254",
        true
    )
    .is_err());
}
#[test]
fn an_empty_or_non_string_url_is_rejected() {
    assert!(validate("", "", false).is_err()); /* Non-string arguments are rejected by the Rust type system. */
}
#[test]
fn a_traversing_filename_is_refused() {
    let root = tempfile::tempdir().unwrap();
    for s in [
        "../secret.txt",
        "../../etc/passwd",
        "..",
        "",
        "sub/dir.xml",
        "a\\b.xml",
    ] {
        assert!(resolve_feed_file(root.path(), s).is_err());
    }
}
#[test]
fn a_real_feed_file_is_served() {
    let root = tempfile::tempdir().unwrap();
    std::fs::write(root.path().join("abc12345_google.xml"), "<rss/>").unwrap();
    assert_eq!(
        resolve_feed_file(root.path(), "abc12345_google.xml")
            .unwrap()
            .file_name()
            .unwrap(),
        "abc12345_google.xml"
    );
}
#[test]
fn a_missing_feed_file_is_a_404() {
    let root = tempfile::tempdir().unwrap();
    assert!(resolve_feed_file(root.path(), "nope.xml").is_err());
}
#[test]
fn any_private_dns_answer_is_rejected() {
    assert!(
        validate_with("https://shop.myshopify.com", "", false, true, |_, p| Ok(
            vec![([93, 184, 216, 34], p).into(), ([127, 0, 0, 1], p).into()]
        ))
        .is_err()
    );
}
#[test]
fn mapped_ipv6_and_reserved_ranges_are_rejected() {
    for s in [
        "::ffff:127.0.0.1",
        "::",
        "fc00::1",
        "fe80::1",
        "ff02::1",
        "2001:db8::1",
        "2002::1",
        "192.88.99.1",
        "192.0.2.1",
        "198.51.100.1",
        "203.0.113.1",
        "224.0.0.1",
        "240.0.0.1",
    ] {
        assert!(ip_forbidden(s.parse().unwrap()), "{s}");
    }
    assert!(!ip_forbidden("93.184.216.34".parse().unwrap()));
}
#[cfg(unix)]
#[test]
fn symlink_outside_feed_directory_is_rejected() {
    let root = tempfile::tempdir().unwrap();
    let outside = tempfile::NamedTempFile::new().unwrap();
    std::os::unix::fs::symlink(outside.path(), root.path().join("escape.xml")).unwrap();
    assert!(resolve_feed_file(root.path(), "escape.xml").is_err());
}
