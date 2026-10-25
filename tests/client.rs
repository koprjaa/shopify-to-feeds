// Project: shopify-to-feeds
// File: tests/client.rs
// Description: Local HTTP mocks for headers, pagination, retry and timeout settings.
// Author: Jan Alexandr Kopřiva
// License: AGPL-3.0-or-later
use serde_json::Value;
use shopify_to_feeds::{
    client::{ShopifyClient, Transport, DEFAULT_USER_AGENT},
    Result,
};
use std::{sync::Mutex, time::Duration};
struct MockHttp {
    waits: Mutex<Vec<Duration>>,
}
impl Transport for MockHttp {
    fn get(&self, url: &str, ua: &str) -> Result<Value> {
        Ok(shopify_to_feeds::client::http_client_builder()
            .build()?
            .get(url)
            .header("User-Agent", ua)
            .send()?
            .error_for_status()?
            .json()?)
    }
    fn wait(&self, d: Duration) {
        self.waits.lock().unwrap().push(d);
    }
}
fn client(base: &str) -> ShopifyClient<MockHttp> {
    ShopifyClient::with_transport(
        base,
        MockHttp {
            waits: Mutex::new(vec![]),
        },
    )
}
#[test]
fn pagination_headers_and_shop_info_are_offline() {
    let server = httpmock::MockServer::start();
    let first = server.mock(|when, then| {
        when.method("GET")
            .path("/products.json")
            .query_param("page", "1")
            .query_param("limit", "250")
            .header("user-agent", DEFAULT_USER_AGENT);
        then.json_body(serde_json::json!({"products":[{"id":1}]}));
    });
    let last = server.mock(|when, then| {
        when.method("GET")
            .path("/products.json")
            .query_param("page", "2");
        then.json_body(serde_json::json!({"products":[]}));
    });
    let shop = server.mock(|when, then| {
        when.method("GET")
            .path("/products.json")
            .query_param("limit", "1");
        then.json_body(serde_json::json!({"products":[{"vendor":"Brand"}]}));
    });
    let c = client(&server.base_url());
    assert_eq!(c.products(None).count(), 1);
    assert_eq!(c.shop_info()["name"], "Brand");
    first.assert_calls(1);
    last.assert_calls(1);
    shop.assert_calls(1);
}
#[test]
fn three_attempts_and_exponential_delays_on_http_errors() {
    let server = httpmock::MockServer::start();
    let m = server.mock(|when, then| {
        when.path("/broken");
        then.status(503);
    });
    let c = client(&server.base_url());
    assert!(c.request("/broken").is_none());
    m.assert_calls(3);
    assert_eq!(
        *c.transport.waits.lock().unwrap(),
        vec![Duration::from_secs(5), Duration::from_secs(10)]
    );
}
#[test]
fn invalid_json_is_retried_and_redirect_is_not_followed() {
    let server = httpmock::MockServer::start();
    let m = server.mock(|when, then| {
        when.path("/bad");
        then.body("not JSON");
    });
    let c = client(&server.base_url());
    assert!(c.request("/bad").is_none());
    m.assert_calls(3);
    let target = server.mock(|when, then| {
        when.path("/target");
        then.json_body(serde_json::json!({}));
    });
    let redirect = server.mock(|when, then| {
        when.path("/redirect");
        then.status(302).header("location", "/target");
    });
    assert!(c.request("/redirect").is_none());
    redirect.assert_calls(3);
    target.assert_calls(0);
}
#[test]
fn successful_retry_returns_data_and_zero_attempts_returns_none() {
    struct Flaky(Mutex<usize>, Mutex<Vec<Duration>>);
    impl Transport for Flaky {
        fn get(&self, _: &str, _: &str) -> Result<Value> {
            let mut n = self.0.lock().unwrap();
            *n += 1;
            if *n < 3 {
                Err("temporary failure".into())
            } else {
                Ok(serde_json::json!({"ok":true}))
            }
        }
        fn wait(&self, d: Duration) {
            self.1.lock().unwrap().push(d);
        }
    }
    let mut c = ShopifyClient::with_transport(
        "https://shop.myshopify.com",
        Flaky(Mutex::new(0), Mutex::new(vec![])),
    );
    c.retry_delay = 2;
    c.user_agent = "custom-agent".into();
    assert_eq!(c.request("/data").unwrap()["ok"], true);
    assert_eq!(
        *c.transport.1.lock().unwrap(),
        vec![Duration::from_secs(2), Duration::from_secs(4)]
    );
    c.max_retries = 0;
    assert!(c.request("/data").is_none());
}
#[test]
fn production_transport_rejects_private_destination_before_fetching() {
    let c = ShopifyClient::new("https://127.0.0.1");
    assert!(c.request("/products.json").is_none());
}

#[test]
fn products_are_lazy_and_stop_fetching_when_consumer_stops() {
    let server = httpmock::MockServer::start();
    let first = server.mock(|w, t| {
        w.path("/products.json").query_param("page", "1");
        t.json_body(serde_json::json!({"products":[{"id":1}]}));
    });
    let later = server.mock(|w, t| {
        w.path("/products.json").query_param("page", "2");
        t.json_body(serde_json::json!({"products":[]}));
    });
    let c = client(&server.base_url());
    let mut iter = c.products(None);
    first.assert_calls(0);
    assert!(iter.next().is_some());
    drop(iter);
    first.assert_calls(1);
    later.assert_calls(0);
    assert_eq!(
        shopify_to_feeds::client::REQUEST_TIMEOUT,
        Duration::from_secs(30)
    );
}

#[test]
fn response_charsets_and_bom_are_decoded_without_live_network() {
    use shopify_to_feeds::client::decode_response;
    let server = httpmock::MockServer::start();
    server.mock(|w, t| {
        w.path("/latin1");
        t.header("content-type", "application/json; charset=iso-8859-1")
            .body(b"{\"text\":\"caf\xe9\"}");
    });
    server.mock(|w, t| {
        w.path("/bom");
        t.header("content-type", "application/json")
            .body(b"\xef\xbb\xbf{\"text\":\"ok\"}");
    });
    let http = shopify_to_feeds::client::http_client_builder()
        .build()
        .unwrap();
    assert_eq!(
        decode_response(http.get(server.url("/latin1")).send().unwrap()).unwrap()["text"],
        "café"
    );
    assert_eq!(
        decode_response(http.get(server.url("/bom")).send().unwrap()).unwrap()["text"],
        "ok"
    );
}

#[test]
fn retry_after_is_read_and_capped() {
    use reqwest::header::{HeaderMap, HeaderValue, RETRY_AFTER};
    use shopify_to_feeds::client::retry_after;
    use std::time::Duration;
    let mut h = HeaderMap::new();
    assert_eq!(retry_after(&h), Duration::ZERO);
    h.insert(RETRY_AFTER, HeaderValue::from_static("7"));
    assert_eq!(retry_after(&h), Duration::from_secs(7));
    h.insert(RETRY_AFTER, HeaderValue::from_static("86400"));
    assert_eq!(retry_after(&h), Duration::from_secs(60));
    h.insert(
        RETRY_AFTER,
        HeaderValue::from_static("Wed, 21 Oct 2026 07:28:00 GMT"),
    );
    assert_eq!(retry_after(&h), Duration::ZERO);
}
