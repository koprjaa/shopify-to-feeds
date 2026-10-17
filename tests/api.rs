// Project: shopify-to-feeds
// File: tests/api.rs
// Description: HTTP contracts, background work, concurrency and cache eviction.
// Author: Jan Alexandr Kopřiva
// Based on shopify-to-feeds by Jan Alexandr Kopřiva
// License: MIT

use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use serde_json::{json, Value};
use shopify_to_feeds::{api::*, security};
use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
    time::Duration,
};
use tower::ServiceExt;
async fn request(app: axum::Router, method: &str, path: &str, key: bool) -> (StatusCode, Value) {
    let mut req = Request::builder().method(method).uri(path);
    if key {
        req = req.header("x-api-key", "test-only-key");
    }
    let res = app.oneshot(req.body(Body::empty()).unwrap()).await.unwrap();
    let status = res.status();
    let bytes = to_bytes(res.into_body(), usize::MAX).await.unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or_else(|_| json!(String::from_utf8_lossy(&bytes))),
    )
}
#[tokio::test]
async fn http_contract_and_background_jobs() {
    let root = tempfile::tempdir().unwrap();
    let mut state = AppState::new(root.path().into(), 1000, 86400, 4);
    state.validate_store = Arc::new(|s| {
        security::validate_with(s, "", false, true, |_, p| {
            Ok(vec![([93, 184, 216, 34], p).into()])
        })
        .map(|r| r.0)
    });
    state.generate_feed =
        Arc::new(|_, _, path, _| shopify_to_feeds::feeds::publish(path, b"<rss />"));
    let app = router(state.clone());
    std::env::remove_var("FEED_API_KEY");
    assert_eq!(
        request(app.clone(), "GET", "/feed/status/any", false)
            .await
            .0,
        503
    );
    std::env::set_var("FEED_API_KEY", "test-only-key");
    assert_eq!(
        request(app.clone(), "GET", "/feed/status/any", false)
            .await
            .0,
        401
    );
    assert_eq!(
        request(app.clone(), "GET", "/feed/status/any", true).await,
        (StatusCode::NOT_FOUND, json!({"detail":"Feed not found"}))
    );
    let (code, body) = request(app.clone(), "GET", "/", false).await;
    assert_eq!(code, 200);
    assert_eq!(body["supported_feeds"], json!(["google", "bing", "zbozi"]));
    assert_eq!(body["version"], "1.0.0");
    assert_eq!(
        request(
            app.clone(),
            "POST",
            "/feed/update/shop.myshopify.com?feed_type=no",
            true
        )
        .await
        .0,
        400
    );
    assert_eq!(
        request(app.clone(), "POST", "/feed/update/example.com", true)
            .await
            .0,
        400
    );
    let (code, body) = request(
        app.clone(),
        "POST",
        "/feed/update/shop.myshopify.com?download_images=false",
        true,
    )
    .await;
    assert_eq!(code, 200);
    assert_eq!(
        body,
        json!({"message":"Feed update started","store_url":"https://shop.myshopify.com","feed_type":"google","feed_url":feed_url("https://shop.myshopify.com","google"),"download_images":false})
    );
    let mut completed = false;
    for _ in 0..100 {
        let (_, body) = request(
            app.clone(),
            "GET",
            "/feed/status/https://shop.myshopify.com",
            true,
        )
        .await;
        if body["status"] == "completed" {
            assert_eq!(body["download_images"], false);
            assert!(body["last_update"].as_str().unwrap().contains('T'));
            completed = true;
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    assert!(completed);
    let path = feed_url("https://shop.myshopify.com", "google");
    let res = app
        .clone()
        .oneshot(Request::builder().uri(&path).body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(res.status(), 200);
    assert_eq!(res.headers()["content-type"], "application/xml");
    assert_eq!(
        to_bytes(res.into_body(), usize::MAX).await.unwrap(),
        "<rss />"
    );
    assert_eq!(
        request(app.clone(), "GET", "/feeds/nope.xml", false)
            .await
            .0,
        404
    );
    state.generate_feed = Arc::new(|_, _, _, _| Err("private internal error".into()));
    tokio::task::spawn_blocking({
        let state = state.clone();
        move || {
            update_feed(
                &state,
                "https://shop.myshopify.com",
                shopify_to_feeds::feeds::FeedType::Bing,
                true,
            )
        }
    })
    .await
    .unwrap();
    let value = state.cache.lock().unwrap().entries["https://shop.myshopify.com"].clone();
    assert_eq!(value["status"], "error");
    assert!(value.get("feed_url").is_none());
    assert!(!value.to_string().contains("private internal"));
    assert_eq!(
        request(
            app.clone(),
            "POST",
            "/feed/update/shop.myshopify.com?download_images=invalid",
            true
        )
        .await
        .0,
        422
    );
    assert_eq!(
        request(
            app.clone(),
            "POST",
            "/feed/update/shop.myshopify.com?download_images=invalid",
            false
        )
        .await
        .0,
        401
    );
    let (code, schema) = request(app.clone(), "GET", "/openapi.json", false).await;
    assert_eq!(code, 200);
    assert_eq!(schema["info"]["version"], "1.0.0");
    for path in ["/docs", "/redoc"] {
        assert_eq!(request(app.clone(), "GET", path, false).await.0, 200);
    }
    let response = app
        .clone()
        .oneshot(
            Request::builder()
                .uri(&path)
                .header("range", "bytes=0-3")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), 206);
    assert_eq!(
        to_bytes(response.into_body(), usize::MAX).await.unwrap(),
        "<rss"
    );
    let response = app
        .oneshot(
            Request::builder()
                .method("HEAD")
                .uri(&path)
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    assert!(response.headers().contains_key("etag"));
    assert!(response.headers().contains_key("last-modified"));
    assert_eq!(
        to_bytes(response.into_body(), usize::MAX)
            .await
            .unwrap()
            .len(),
        0
    );
    std::env::remove_var("FEED_API_KEY");
}
#[test]
fn background_concurrency_cap_and_invalid_urls_record_sanitized_errors() {
    let root = tempfile::tempdir().unwrap();
    let mut state = AppState::new(root.path().into(), 1000, 86400, 0);
    state.validate_store = Arc::new(|s| Ok(s.into()));
    state.generate_feed = Arc::new(|_, _, _, _| panic!("must not run"));
    update_feed(
        &state,
        "https://shop.myshopify.com",
        shopify_to_feeds::feeds::FeedType::Google,
        true,
    );
    assert_eq!(
        state.cache.lock().unwrap().entries["https://shop.myshopify.com"]["status"],
        "error"
    );
    state.validate_store = Arc::new(|_| Err("rejected".into()));
    update_feed(
        &state,
        "bad",
        shopify_to_feeds::feeds::FeedType::Google,
        true,
    );
    assert_eq!(
        state.cache.lock().unwrap().entries["bad"]["status"],
        "error"
    );
}
#[test]
fn cache_eviction_matches_age_count_and_update_rules() {
    let now =
        chrono::NaiveDateTime::parse_from_str("2026-01-02T00:00:00", "%Y-%m-%dT%H:%M:%S").unwrap();
    let mut cache = StateCache {
        entries: HashMap::new(),
        max: 3,
        ttl: Duration::from_secs(10),
    };
    cache.set(
        "expired".into(),
        json!({"last_update":"2026-01-01T23:59:49"}),
        now,
    );
    assert!(cache.entries.is_empty());
    cache.set(
        "boundary".into(),
        json!({"last_update":"2026-01-01T23:59:50"}),
        now,
    );
    assert!(cache.entries.contains_key("boundary"));
    cache.set(
        "just_expired".into(),
        json!({"last_update":"2026-01-01T23:59:49.999999"}),
        now,
    );
    assert!(!cache.entries.contains_key("just_expired"));
    cache.set("invalid".into(), json!({"last_update":"invalid"}), now);
    cache.set("missing".into(), json!({}), now);
    cache.set(
        "new".into(),
        json!({"last_update":"2026-01-02T00:00:00"}),
        now,
    );
    assert_eq!(cache.entries.len(), 3);
    assert!(!cache.entries.contains_key("missing"));
    cache.update("new", json!({"status":"completed"}));
    assert_eq!(cache.entries["new"]["status"], "completed");
    cache.update("absent", json!({"status":"error"}));
    assert!(!cache.entries.contains_key("absent"));
}
#[test]
fn filename_is_original_md5_prefix() {
    assert_eq!(
        feed_filename("https://example.myshopify.com", "google"),
        format!(
            "{}_google.xml",
            &format!("{:x}", md5::compute("https://example.myshopify.com"))[..8]
        )
    );
}
#[test]
fn concurrent_cache_writes_remain_bounded() {
    let cache = Arc::new(Mutex::new(StateCache {
        entries: HashMap::new(),
        max: 10,
        ttl: Duration::from_secs(100),
    }));
    std::thread::scope(|scope| {
        for i in 0..100 {
            let cache = cache.clone();
            scope.spawn(move || {
                cache.lock().unwrap().set(
                    i.to_string(),
                    json!({"last_update":"invalid"}),
                    chrono::Local::now().naive_local(),
                )
            });
        }
    });
    assert_eq!(cache.lock().unwrap().entries.len(), 10);
}
