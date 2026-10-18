// Project: shopify-to-feeds
// File: tests/audit.rs
// Description: Differential regressions captured from the original Python implementation.
// Author: Jan Alexandr Kopřiva
// License: MIT

use serde_json::{json, Value};
use shopify_to_feeds::{
    feeds::{process_product, FeedType},
    helpers::{format_price, remove_html_tags},
};
#[test]
fn python_helper_oracle() {
    let oracle: Value = serde_json::from_str(include_str!("fixtures/audit_oracle.json")).unwrap();
    for case in oracle["prices"].as_array().unwrap() {
        assert_eq!(
            format_price(&case[0], "CZK"),
            case[1],
            "price {:?}",
            case[0]
        );
    }
    for case in oracle["descriptions"].as_array().unwrap() {
        assert_eq!(
            remove_html_tags(&case[0], None),
            case[1],
            "description {:?}",
            case[0]
        );
    }
}
#[test]
fn python_product_oracle() {
    let oracle: Value = serde_json::from_str(include_str!("fixtures/audit_oracle.json")).unwrap();
    for case in oracle["products"].as_array().unwrap() {
        let kind = FeedType::parse(case["kind"].as_str().unwrap()).unwrap();
        let mut product: Value =
            serde_json::from_str(include_str!("fixtures/product.json")).unwrap();
        let field = case["field"].as_str().unwrap();
        if field == "price" {
            product["variants"][0][field] = case["value"].clone();
        } else {
            product[field] = case["value"].clone();
        }
        let actual = process_product(kind, "https://shop.myshopify.com", "CZK", &product);
        let actual = match actual {
            Err(_) => Value::Null,
            Ok(nodes) => Value::Array(
                nodes
                    .into_iter()
                    .map(|n| {
                        let mut map = serde_json::Map::new();
                        for child in n.children {
                            if child.children.is_empty()
                                && ![
                                    "g:additional_image_link",
                                    "AdditionalImageLink",
                                    "IMGURL_ALTERNATIVE",
                                ]
                                .contains(&child.name.as_str())
                            {
                                map.insert(
                                    child.name.trim_start_matches("g:").into(),
                                    json!(child.text),
                                );
                            }
                        }
                        Value::Object(map)
                    })
                    .collect(),
            ),
        };
        assert_eq!(
            actual, case["expected"],
            "{} {}={}",
            case["kind"], case["field"], case["value"]
        );
    }
}

#[tokio::test]
async fn python_query_oracle() {
    use axum::{
        body::{to_bytes, Body},
        http::Request,
    };
    use shopify_to_feeds::api::{router, AppState};
    use std::sync::Arc;
    use tower::ServiceExt;
    let oracle: Value = serde_json::from_str(include_str!("fixtures/audit_oracle.json")).unwrap();
    let root = tempfile::tempdir().unwrap();
    let mut state = AppState::new(root.path().into(), 1000, 86400, 4);
    state.validate_store = Arc::new(|_| Ok("https://shop.myshopify.com".into()));
    state.generate_feed = Arc::new(|_, _, _, _| Ok(()));
    std::env::set_var("FEED_API_KEY", "test-only-key");
    for case in oracle["queries"].as_array().unwrap() {
        let response = router(state.clone())
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!(
                        "/feed/update/shop.myshopify.com?{}",
                        case["query"].as_str().unwrap()
                    ))
                    .header("x-api-key", "test-only-key")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(
            response.status().as_u16(),
            case["status"].as_u64().unwrap() as u16
        );
        let body: Value =
            serde_json::from_slice(&to_bytes(response.into_body(), usize::MAX).await.unwrap())
                .unwrap();
        assert_eq!(body, case["body"], "{}", case["query"]);
    }
    std::env::remove_var("FEED_API_KEY");
}

#[test]
fn python_cli_exit_codes() {
    let oracle: Value = serde_json::from_str(include_str!("fixtures/audit_oracle.json")).unwrap();
    for case in oracle["cli"].as_array().unwrap() {
        let root = tempfile::tempdir().unwrap();
        let mut args: Vec<String> = case["args"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().into())
            .collect();
        if let Some(i) = args.iter().position(|a| a == "-o") {
            args[i + 1] = root.path().to_string_lossy().into();
        }
        let result = std::process::Command::new(env!("CARGO_BIN_EXE_smoke_feeds"))
            .args(args)
            .env_remove("FEED_ALLOWED_HOSTS")
            .output()
            .unwrap();
        assert_eq!(
            result.status.code().unwrap(),
            case["status"].as_i64().unwrap() as i32
        );
    }
}

#[test]
fn python_local_http_oracle() {
    use shopify_to_feeds::client::{http_client_builder, ShopifyClient, Transport};
    use std::time::Duration;
    struct Local;
    impl Transport for Local {
        fn get(&self, url: &str, _: &str) -> shopify_to_feeds::Result<Value> {
            Ok(http_client_builder()
                .build()?
                .get(url)
                .send()?
                .error_for_status()?
                .json()?)
        }
        fn wait(&self, _: Duration) {}
    }
    let server = httpmock::MockServer::start();
    for (path, status, body) in [
        ("/ok", 200, r#"{"value":"ok"}"#),
        ("/bad", 200, "broken"),
        ("/unavailable", 503, "{}"),
        ("/redirect", 302, r#"{"value":"redirect"}"#),
    ] {
        server.mock(|w, t| {
            w.path(path);
            t.status(status).body(body);
        });
    }
    let oracle: Value = serde_json::from_str(include_str!("fixtures/audit_oracle.json")).unwrap();
    let client = ShopifyClient::with_transport(&server.base_url(), Local);
    for case in oracle["network"].as_array().unwrap() {
        assert_eq!(
            client
                .request(case["path"].as_str().unwrap())
                .unwrap_or(Value::Null),
            case["expected"]
        );
    }
}

#[test]
fn python_weight_oracle() {
    let oracle: Value = serde_json::from_str(include_str!("fixtures/audit_oracle.json")).unwrap();
    for case in oracle["weights"].as_array().unwrap() {
        let actual = shopify_to_feeds::helpers::format_weight(
            &case["value"],
            case["unit"].as_str().unwrap(),
        )
        .unwrap();
        assert_eq!(json!(actual), case["expected"], "{case}");
    }
}

#[test]
fn python_json_encoding_oracle() {
    let oracle: Value = serde_json::from_str(include_str!("fixtures/audit_oracle.json")).unwrap();
    for case in oracle["encodings"].as_array().unwrap() {
        let bytes: Vec<u8> = case["bytes"]
            .as_array()
            .unwrap()
            .iter()
            .map(|n| n.as_u64().unwrap() as u8)
            .collect();
        assert_eq!(
            shopify_to_feeds::client::decode_json(&bytes).unwrap(),
            case["expected"],
            "{}",
            case["encoding"]
        );
    }
    for bytes in [
        vec![],
        vec![0xff, 0xfe, 0],
        vec![0, 0, 0xfe, 0xff, 0, 0, 0xd8, 0],
    ] {
        assert!(shopify_to_feeds::client::decode_json(&bytes).is_err());
    }
}

#[test]
fn retained_python_bug_fixtures_explain_xml_corrections() {
    let google = include_str!("fixtures/python_google.xml");
    let zbozi = include_str!("fixtures/python_zbozi.xml");
    assert_eq!(google.matches("xmlns:g=").count(), 2);
    assert!(zbozi.contains("<PARAM>{'PARAM_NAME':"));
    assert!(!zbozi.contains("<DELIVERY_ID>ZASILKOVNA"));
    let p: Value = serde_json::from_str(include_str!("fixtures/product.json")).unwrap();
    for kind in [FeedType::Google, FeedType::Zbozi] {
        let xml = shopify_to_feeds::feeds::render(
            kind,
            "https://shop.myshopify.com",
            &json!({}),
            process_product(kind, "https://shop.myshopify.com", "CZK", &p).unwrap(),
        )
        .unwrap();
        if kind == FeedType::Google {
            assert_eq!(xml.matches("xmlns:g=").count(), 1);
        } else {
            assert!(xml.contains("<PARAM><PARAM_NAME>"));
            assert!(xml.contains("<DELIVERY_ID>ZASILKOVNA"));
        }
    }
}
