// Project: shopify-to-feeds
// File: src/api.rs
// Description: HTTP service, bounded background jobs and feed-state cache.
// Author: Jan Alexandr Kopřiva
// Based on shopify-to-feeds by Jan Alexandr Kopřiva
// License: MIT

use crate::{
    client::ShopifyClient,
    feeds::{self, FeedType},
    log, security, Result,
};
use axum::{
    extract::{Path, Query, State},
    http::{header, HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    path::{Path as FilePath, PathBuf},
    sync::{Arc, Mutex},
    time::Duration,
};

type ApiError = (StatusCode, Json<Value>);
fn error(code: u16, message: impl ToString) -> ApiError {
    (
        StatusCode::from_u16(code).unwrap(),
        Json(json!({"detail":message.to_string()})),
    )
}
fn now() -> String {
    chrono::Local::now()
        .naive_local()
        .format("%Y-%m-%dT%H:%M:%S%.6f")
        .to_string()
}
pub fn feed_filename(store: &str, kind: &str) -> String {
    format!(
        "{:.8}_{kind}.xml",
        format!("{:x}", md5::compute(store.as_bytes()))
    )
}
pub fn feed_url(store: &str, kind: &str) -> String {
    format!("/feeds/{}", feed_filename(store, kind))
}
pub struct StateCache {
    pub entries: HashMap<String, Value>,
    pub max: usize,
    pub ttl: Duration,
}
impl StateCache {
    pub fn set(&mut self, key: String, value: Value, now: chrono::NaiveDateTime) {
        self.entries.insert(key, value);
        self.entries.retain(|_, v| {
            v["last_update"]
                .as_str()
                .and_then(|s| chrono::NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M:%S%.f").ok())
                .is_none_or(|t| {
                    chrono::Duration::from_std(self.ttl)
                        .map_or(true, |ttl| now.signed_duration_since(t) <= ttl)
                })
        });
        let mut keys: Vec<_> = self
            .entries
            .iter()
            .map(|(k, v)| {
                (
                    k.clone(),
                    v["last_update"].as_str().unwrap_or("").to_string(),
                )
            })
            .collect();
        keys.sort_by(|a, b| a.1.cmp(&b.1).then(a.0.cmp(&b.0)));
        for (key, _) in keys
            .into_iter()
            .take(self.entries.len().saturating_sub(self.max))
        {
            self.entries.remove(&key);
        }
    }
    pub fn update(&mut self, key: &str, updates: Value) {
        if let Some(v) = self.entries.get_mut(key).and_then(Value::as_object_mut) {
            if let Some(updates) = updates.as_object() {
                v.extend(updates.clone());
            }
        }
    }
}
pub type StoreValidator = Arc<dyn Fn(&str) -> Result<String> + Send + Sync>;
pub type FeedJob = Arc<dyn Fn(&str, FeedType, &FilePath, bool) -> Result<()> + Send + Sync>;
#[derive(Clone)]
pub struct AppState {
    pub validate_store: StoreValidator,
    pub generate_feed: FeedJob,
    pub root: PathBuf,
    pub cache: Arc<Mutex<StateCache>>,
    pub semaphore: Arc<tokio::sync::Semaphore>,
}
impl AppState {
    pub fn new(root: PathBuf, max: usize, ttl: u64, concurrent: usize) -> Self {
        Self {
            validate_store: Arc::new(|s| security::validate(s, false).map(|r| r.0)),
            generate_feed: Arc::new(|store, kind, path, images| {
                feeds::generate(&ShopifyClient::new(store), kind, path, "CZK", images, 4)
            }),
            root,
            cache: Arc::new(Mutex::new(StateCache {
                entries: HashMap::new(),
                max,
                ttl: Duration::from_secs(ttl),
            })),
            semaphore: Arc::new(tokio::sync::Semaphore::new(concurrent)),
        }
    }
    pub fn from_env() -> Result<Self> {
        fn number(name: &str, default: &str) -> Result<u64> {
            Ok(std::env::var(name)
                .unwrap_or_else(|_| default.into())
                .parse()?)
        }
        let state = Self::new(
            PathBuf::from("static/feeds"),
            number("FEED_STATES_MAX", "1000")? as usize,
            number("FEED_STATES_TTL", "86400")?,
            number("FEED_MAX_CONCURRENT", "4")? as usize,
        );
        std::fs::create_dir_all(&state.root)?;
        Ok(state)
    }
    pub fn set(&self, store: &str, value: Value) {
        self.cache
            .lock()
            .unwrap()
            .set(store.into(), value, chrono::Local::now().naive_local());
    }
}
fn auth(headers: &HeaderMap) -> std::result::Result<(), ApiError> {
    security::authenticate(
        std::env::var("FEED_API_KEY").ok().as_deref(),
        headers.get("x-api-key").and_then(|v| v.to_str().ok()),
    )
    .map_err(|(c, m)| error(c, m))
}
#[derive(Deserialize)]
struct UpdateQuery {
    #[serde(default = "default_kind")]
    feed_type: String,
    #[serde(default = "default_images", deserialize_with = "query_bool")]
    download_images: bool,
}
fn default_kind() -> String {
    "google".into()
}
fn default_images() -> bool {
    true
}
fn query_bool<'de, D: serde::Deserializer<'de>>(d: D) -> std::result::Result<bool, D::Error> {
    let s = String::deserialize(d)?;
    match s.to_lowercase().as_str() {
        "true" | "1" | "on" | "yes" => Ok(true),
        "false" | "0" | "off" | "no" => Ok(false),
        _ => Err(serde::de::Error::custom("Input should be a valid boolean")),
    }
}
async fn trigger(
    State(state): State<AppState>,
    Path(store): Path<String>,
    headers: HeaderMap,
    query: std::result::Result<Query<UpdateQuery>, axum::extract::rejection::QueryRejection>,
) -> std::result::Result<Json<Value>, ApiError> {
    auth(&headers)?;
    let q = query.map_err(|_| (StatusCode::UNPROCESSABLE_ENTITY, Json(json!({"detail":[{"type":"bool_parsing","loc":["query","download_images"],"msg":"Input should be a valid boolean, unable to interpret input"}]}))))?.0;
    let kind = FeedType::parse(&q.feed_type)
        .map_err(|_| error(400, "Invalid feed type. Must be: google, bing, or zbozi"))?;
    let validator = state.validate_store.clone();
    let store = tokio::task::spawn_blocking(move || validator(&store))
        .await
        .map_err(|_| error(500, "Internal Server Error"))?
        .map_err(|e| error(400, format!("Invalid store URL: {e}")))?;
    let response = json!({"message":"Feed update started","store_url":store,"feed_type":q.feed_type,"feed_url":feed_url(&store,&q.feed_type),"download_images":q.download_images});
    tokio::task::spawn_blocking(move || update_feed(&state, &store, kind, q.download_images));
    Ok(Json(response))
}
pub fn update_feed(state: &AppState, store: &str, kind: FeedType, images: bool) {
    let store = match (state.validate_store)(store) {
        Ok(v) => v,
        Err(e) => {
            log(
                "WARNING",
                format!("Rejected feed update for invalid store URL: {e}"),
            );
            state.set(store, json!({"status":"error","last_update":now()}));
            return;
        }
    };
    let Ok(_permit) = state.semaphore.try_acquire() else {
        log("WARNING", "Feed task rejected: concurrency cap reached");
        state.set(&store, json!({"status":"error","last_update":now()}));
        return;
    };
    state.set(&store,json!({"status":"processing","last_update":now(),"feed_url":feed_url(&store,kind.name()),"download_images":images}));
    let result = (state.generate_feed)(
        &store,
        kind,
        &state.root.join(feed_filename(&store, kind.name())),
        images,
    );
    if let Err(e) = result {
        log("ERROR", format!("Error updating feed: {e}"));
        state.set(&store, json!({"status":"error","last_update":now()}));
    } else {
        state
            .cache
            .lock()
            .unwrap()
            .update(&store, json!({"status":"completed","last_update":now()}));
        log(
            "INFO",
            format!("Feed generation completed for {store} ({})", kind.name()),
        );
    }
}
async fn status(
    State(state): State<AppState>,
    Path(store): Path<String>,
    headers: HeaderMap,
) -> std::result::Result<Json<Value>, ApiError> {
    auth(&headers)?;
    state
        .cache
        .lock()
        .unwrap()
        .entries
        .get(&store)
        .cloned()
        .map(Json)
        .ok_or_else(|| error(404, "Feed not found"))
}
async fn file(
    State(state): State<AppState>,
    Path(filename): Path<String>,
    request: axum::extract::Request,
) -> std::result::Result<Response, ApiError> {
    let path = security::resolve_feed_file(&state.root, &filename)
        .map_err(|_| error(404, "Feed file not found"))?;
    let metadata = tokio::fs::metadata(&path)
        .await
        .map_err(|_| error(404, "Feed file not found"))?;
    let mut response = tower_http::services::ServeFile::new(path)
        .try_call(request)
        .await
        .map_err(|_| error(404, "Feed file not found"))?
        .into_response();
    response.headers_mut().insert(
        header::CONTENT_TYPE,
        axum::http::HeaderValue::from_static("application/xml"),
    );
    if let Ok(modified) = metadata.modified().and_then(|t| {
        t.duration_since(std::time::UNIX_EPOCH)
            .map_err(std::io::Error::other)
    }) {
        let tag = format!(
            "\"{:x}\"",
            md5::compute(format!("{:?}-{}", modified.as_secs_f64(), metadata.len()))
        );
        if let Ok(tag) = axum::http::HeaderValue::from_str(&tag) {
            response.headers_mut().insert(header::ETAG, tag);
        }
    }
    Ok(response)
}
async fn root() -> Json<Value> {
    Json(
        json!({"name":"Shopify to Feeds API","version":"1.0.0","description":"Universal tool for generating product feeds from Shopify stores","endpoints":{"update_feed":"POST /feed/update/{store_url}?feed_type=google&download_images=true","feed_status":"GET /feed/status/{store_url}","get_feed":"GET /feeds/{filename}"},"supported_feeds":["google","bing","zbozi"]}),
    )
}
pub fn router(state: AppState) -> Router {
    Router::new()
        .route("/", get(root))
        .route("/openapi.json", get(openapi))
        .route("/docs", get(docs))
        .route("/docs/oauth2-redirect", get(oauth_redirect))
        .route("/redoc", get(redoc))
        .route("/feed/update/{*store}", post(trigger))
        .route("/feed/status/{*store}", get(status))
        .route("/feeds/{filename}", get(file))
        .with_state(state)
}

async fn openapi() -> Json<Value> {
    Json(serde_json::from_str(include_str!("openapi.json")).expect("embedded API schema"))
}
async fn docs() -> axum::response::Html<&'static str> {
    axum::response::Html(
        r#"<!DOCTYPE html><html><head><title>Shopify to Feeds API - Swagger UI</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"></head><body><div id="swagger-ui"></div><script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script><script>SwaggerUIBundle({url:'/openapi.json',dom_id:'#swagger-ui',deepLinking:true,oauth2RedirectUrl:window.location.origin+'/docs/oauth2-redirect',presets:[SwaggerUIBundle.presets.apis,SwaggerUIBundle.SwaggerUIStandalonePreset]})</script></body></html>"#,
    )
}
async fn oauth_redirect() -> axum::response::Html<&'static str> {
    axum::response::Html("<!DOCTYPE html><html><head><title>Swagger UI OAuth2 redirect</title></head><body><script>window.close();</script></body></html>")
}
async fn redoc() -> axum::response::Html<&'static str> {
    axum::response::Html(
        r#"<!DOCTYPE html><html><head><title>Shopify to Feeds API - ReDoc</title></head><body><redoc spec-url="/openapi.json"></redoc><script src="https://cdn.jsdelivr.net/npm/redoc@2/bundles/redoc.standalone.js"></script></body></html>"#,
    )
}
