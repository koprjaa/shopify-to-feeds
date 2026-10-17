// Project: shopify-to-feeds
// File: src/client.rs
// Description: Validated Shopify JSON pagination and retry policy.
// Author: Jan Alexandr Kopřiva
// License: MIT

use crate::{log, security, Result};
use serde_json::Value;
use std::time::Duration;

pub const DEFAULT_USER_AGENT: &str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36";
pub trait Transport {
    fn validate(&self, _url: &str) -> Result<()> {
        Ok(())
    }
    fn get(&self, url: &str, user_agent: &str) -> Result<Value>;
    fn wait(&self, delay: Duration) {
        std::thread::sleep(delay);
    }
}
pub const REQUEST_TIMEOUT: Duration = Duration::from_secs(30);
pub fn http_client_builder() -> reqwest::blocking::ClientBuilder {
    reqwest::blocking::Client::builder()
        .timeout(REQUEST_TIMEOUT)
        .connect_timeout(REQUEST_TIMEOUT)
        .redirect(reqwest::redirect::Policy::none())
        .http1_only()
        .no_proxy()
}
pub struct HttpTransport;
impl Transport for HttpTransport {
    fn validate(&self, url: &str) -> Result<()> {
        security::validate(url, false).map(|_| ())
    }
    fn get(&self, input: &str, user_agent: &str) -> Result<Value> {
        let (_, url, addrs) = security::validate(input, false)?;
        let host = url.host_str().ok_or("URL has no host.")?;
        let client = http_client_builder()
            .resolve_to_addrs(host, &addrs)
            .build()?;
        let response = client
            .get(url)
            .header("User-Agent", user_agent)
            .header("Accept", "*/*")
            .header("Connection", "keep-alive")
            .send()?
            .error_for_status()?;
        Ok(serde_json::from_reader(response)?)
    }
}
pub struct ShopifyClient<T = HttpTransport> {
    pub store_url: String,
    pub max_retries: usize,
    pub retry_delay: u64,
    pub user_agent: String,
    pub transport: T,
}
impl ShopifyClient<HttpTransport> {
    pub fn new(store: &str) -> Self {
        Self::with_transport(store, HttpTransport)
    }
}
impl<T: Transport> ShopifyClient<T> {
    pub fn with_transport(store: &str, transport: T) -> Self {
        Self {
            store_url: normalize(store),
            max_retries: 3,
            retry_delay: 5,
            user_agent: DEFAULT_USER_AGENT.into(),
            transport,
        }
    }
    pub fn request(&self, path: &str) -> Option<Value> {
        let url = match reqwest::Url::parse(&self.store_url).and_then(|u| u.join(path)) {
            Ok(u) => u.to_string(),
            Err(e) => {
                log("WARNING", format!("Rejected request URL {path:?}: {e}"));
                return None;
            }
        };
        // Reject invalid destinations before entering retry backoff.
        if let Err(e) = self.transport.validate(&url) {
            log("WARNING", format!("Rejected request URL {url:?}: {e}"));
            return None;
        }
        for attempt in 0..self.max_retries {
            match self.transport.get(&url, &self.user_agent) {
                Ok(value) => return Some(value),
                Err(e) => {
                    log(
                        "WARNING",
                        format!(
                            "Request failed (attempt {}/{}): {e}",
                            attempt + 1,
                            self.max_retries
                        ),
                    );
                    if attempt + 1 < self.max_retries {
                        let delay = self
                            .retry_delay
                            .saturating_mul(2_u64.saturating_pow(attempt as u32));
                        log("INFO", format!("Retrying in {delay} seconds..."));
                        self.transport.wait(Duration::from_secs(delay));
                    }
                }
            }
        }
        log(
            "ERROR",
            format!(
                "Failed to retrieve data from {url} after {} attempts",
                self.max_retries
            ),
        );
        None
    }
    pub fn collections(&self) -> Vec<Value> {
        let mut all = Vec::new();
        for page in 1.. {
            log("INFO", format!("Fetching collections (page {page})"));
            let Some(data) = self.request(&format!("/collections.json?page={page}")) else {
                break;
            };
            let Some(items) = data["collections"].as_array().filter(|a| !a.is_empty()) else {
                break;
            };
            log(
                "INFO",
                format!("Found {} collections on page {page}", items.len()),
            );
            for c in items {
                log(
                    "INFO",
                    format!(
                        "Processing collection: {} ({})",
                        crate::helpers::text(&c["title"]),
                        crate::helpers::text(&c["handle"])
                    ),
                );
                all.push(c.clone());
            }
        }
        log("INFO", format!("Total collections found: {}", all.len()));
        all
    }
    pub fn products<'a>(&'a self, collection: Option<&str>) -> Products<'a, T> {
        Products {
            client: self,
            collection: collection.map(str::to_string),
            page: 1,
            pending: Vec::new().into_iter(),
            done: false,
        }
    }
    pub fn shop_info(&self) -> Value {
        self.request("/products.json?limit=1").and_then(|v| v["products"].as_array()?.first().cloned()).map(|p| serde_json::json!({"name": p.get("vendor").cloned().unwrap_or(Value::String(String::new())),"description":"","url":self.store_url})).unwrap_or_else(|| serde_json::json!({"name":"E-shop","description":"","url":self.store_url}))
    }
}
pub fn normalize(store: &str) -> String {
    let store = if store.starts_with("http://") || store.starts_with("https://") {
        store.into()
    } else {
        format!("https://{store}")
    };
    store.trim_end_matches('/').into()
}

pub struct Products<'a, T> {
    client: &'a ShopifyClient<T>,
    collection: Option<String>,
    page: usize,
    pending: std::vec::IntoIter<Value>,
    done: bool,
}
impl<T: Transport> Iterator for Products<'_, T> {
    type Item = Value;
    fn next(&mut self) -> Option<Value> {
        if let Some(item) = self.pending.next() {
            return Some(item);
        }
        if self.done {
            return None;
        }
        let page = self.page;
        let path = if let Some(h) = &self.collection {
            log(
                "INFO",
                format!("Fetching products from collection: {h} (page {page})"),
            );
            format!("/collections/{h}/products.json?page={page}")
        } else {
            log("INFO", format!("Fetching all products (page {page})"));
            format!("/products.json?page={page}&limit=250")
        };
        let data = self.client.request(&path);
        let items = data
            .as_ref()
            .and_then(|v| v["products"].as_array())
            .filter(|a| !a.is_empty());
        match items {
            Some(items) => {
                log(
                    "INFO",
                    format!("Found {} products on page {page}", items.len()),
                );
                self.pending = items.clone().into_iter();
                self.page += 1;
                self.pending.next()
            }
            None => {
                self.done = true;
                None
            }
        }
    }
}
