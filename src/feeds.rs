// Project: shopify-to-feeds
// File: src/feeds.rs
// Description: Ordered merchant XML mappings and guarded file publication.
// Author: Jan Alexandr Kopřiva
// License: AGPL-3.0-or-later
use crate::{
    client::{ShopifyClient, Transport},
    helpers::{fixed, format_price, number, remove_html_tags, text, truth},
    log, Result,
};
use regex::Regex;
use serde_json::Value;
use std::{
    collections::HashSet,
    io::Write,
    path::Path,
    sync::{atomic::Ordering, LazyLock},
};

#[derive(Clone, Copy, Debug, PartialEq, Eq, clap::ValueEnum)]
pub enum FeedType {
    Google,
    Bing,
    Zbozi,
}
impl FeedType {
    pub fn name(self) -> &'static str {
        match self {
            Self::Google => "google",
            Self::Bing => "bing",
            Self::Zbozi => "zbozi",
        }
    }
    pub fn label(self) -> &'static str {
        match self {
            Self::Google => "Google",
            Self::Bing => "Bing",
            Self::Zbozi => "Zbozi",
        }
    }
    pub fn parse(s: &str) -> Result<Self> {
        match s {
            "google" => Ok(Self::Google),
            "bing" => Ok(Self::Bing),
            "zbozi" => Ok(Self::Zbozi),
            _ => Err(format!("Unknown feed type: {s}").into()),
        }
    }
}
#[derive(Clone, Debug)]
pub struct Node {
    pub attributes: Vec<(String, String)>,
    pub name: String,
    pub text: String,
    pub children: Vec<Node>,
}
impl Node {
    pub fn leaf(name: &str, value: impl Into<String>) -> Self {
        Self {
            attributes: vec![],
            name: name.into(),
            text: value.into(),
            children: vec![],
        }
    }
    pub fn branch(name: &str, children: Vec<Node>) -> Self {
        Self {
            attributes: vec![],
            name: name.into(),
            text: String::new(),
            children,
        }
    }
    fn xml(&self, out: &mut String) {
        out.push('<');
        out.push_str(&self.name);
        for (key, value) in &self.attributes {
            out.push(' ');
            out.push_str(key);
            out.push_str("=\"");
            out.push_str(&escape(value).replace('"', "&quot;"));
            out.push('"');
        }
        if self.text.is_empty() && self.children.is_empty() {
            out.push_str(" />");
            return;
        }
        out.push('>');
        out.push_str(&escape(&self.text));
        for child in &self.children {
            child.xml(out);
        }
        out.push_str("</");
        out.push_str(&self.name);
        out.push('>');
    }
}
fn escape(s: &str) -> String {
    // Characters outside the XML 1.0 Char production make a parser reject the whole feed.
    s.chars()
        .filter(|c| {
            matches!(c, '\t' | '\n' | '\r' | '\u{20}'..='\u{d7ff}' | '\u{e000}'..='\u{fffd}' | '\u{10000}'..='\u{10ffff}')
        })
        .collect::<String>()
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}
fn get(v: &Value, key: &str, default: &str) -> String {
    v.get(key).map(text).unwrap_or_else(|| default.into())
}
fn required(v: &Value, key: &str) -> Result<String> {
    v.get(key)
        .map(text)
        .ok_or_else(|| format!("Missing field: {key}").into())
}
fn integer(v: &Value) -> Result<String> {
    let n = number(v)
        .filter(|n| n.is_finite())
        .ok_or("Invalid numeric price")?;
    // Whole prices stay integers; a fractional price keeps its cents instead of being cut off.
    let rounded = (n * 100.0).round() / 100.0;
    Ok(if rounded == 0.0 {
        "0".into()
    } else if rounded.fract() == 0.0 {
        format!("{rounded:.0}")
    } else {
        format!("{rounded:.2}")
    })
}
fn add(nodes: &mut Vec<Node>, key: &str, value: impl Into<String>) {
    nodes.push(Node::leaf(key, value));
}
fn images(p: &Value, singular: bool) -> Result<Vec<String>> {
    if let Some(a) = p["images"].as_array().filter(|a| !a.is_empty()) {
        let mut links = Vec::new();
        for (index, image) in a.iter().enumerate() {
            let link = required(image, "src")?;
            if !singular || index == 0 || truth(&image["src"]) {
                links.push(link);
            }
        }
        return Ok(links);
    }
    if singular && p.get("image").is_some() {
        return Ok(vec![required(&p["image"], "src")?]);
    }
    Ok(vec![])
}
fn join(store: &str, path: &str) -> Result<String> {
    reqwest::Url::parse(store)?;
    let authority_start = store.find("://").ok_or("URL has no scheme")? + 3;
    let authority_end = store[authority_start..]
        .find(['/', '?', '#'])
        .map_or(store.len(), |i| authority_start + i);
    let path = path.replace(['\t', '\r', '\n'], "");
    let suffix_start = path.find(['?', '#']).unwrap_or(path.len());
    let mut segments = Vec::new();
    let raw_path = &path[..suffix_start];
    for segment in raw_path.split('/') {
        match segment {
            "." => (),
            ".." => {
                if segments.len() > 1 {
                    segments.pop();
                }
            }
            _ => segments.push(segment),
        }
    }
    if raw_path.ends_with("/.") || raw_path.ends_with("/..") {
        segments.push("");
    }
    Ok(format!(
        "{}{}{}",
        &store[..authority_end],
        segments.join("/"),
        &path[suffix_start..]
    ))
}
fn title(p: &Value, v: &Value, google: bool) -> Result<String> {
    let ptitle = if google {
        get(p, "title", "")
    } else {
        required(p, "title")?
    };
    let vtitle = if google {
        get(v, "title", "Default Title")
    } else {
        required(v, "title")?
    };
    if google {
        Ok(format!("{ptitle} - {vtitle}").replace(" - Default Title", ""))
    } else if vtitle == "Default Title" {
        Ok(ptitle)
    } else {
        Ok(format!("{ptitle} - {vtitle}"))
    }
}
pub fn process_product(
    kind: FeedType,
    store: &str,
    currency: &str,
    p: &Value,
) -> Result<Vec<Node>> {
    let mut result = vec![];
    let google_images = if kind == FeedType::Google {
        Some(images(p, true)?)
    } else {
        None
    };
    let variants = match p.get("variants") {
        None => return Ok(result),
        Some(Value::Array(a)) => a,
        _ => return Err("Invalid variants: expected an array".into()),
    };
    // Bing and Zbozi inspect images only when a variant exists.
    if variants.is_empty() && kind != FeedType::Google {
        return Ok(result);
    }
    if kind != FeedType::Google && p.get("images").is_some_and(|v| !v.is_array()) {
        return Err("Invalid images: expected an array".into());
    }
    let imgs = match google_images {
        Some(imgs) => imgs,
        None => images(p, false)?,
    };
    for v in variants {
        if !v.is_object() {
            return Err("Invalid variant: expected an object".into());
        }
        let mapped = (|| -> Result<Node> {
            let mut n = vec![];
            let product_title = title(p, v, kind == FeedType::Google)?;
            let available = truth(&v["available"]);
            let id = if kind == FeedType::Google {
                get(v, "id", "")
            } else {
                required(v, "id")?
            };
            let handle = if kind == FeedType::Google {
                get(p, "handle", "")
            } else {
                required(p, "handle")?
            };
            let link = join(
                store,
                &format!(
                    "/products/{handle}{}",
                    if kind == FeedType::Google {
                        String::new()
                    } else {
                        format!("?variant={id}")
                    }
                ),
            )?;
            let image = imgs.first().cloned().unwrap_or_default();
            match kind {
                FeedType::Google => {
                    add(&mut n, "g:id", id);
                    add(&mut n, "g:title", product_title);
                    add(
                        &mut n,
                        "g:description",
                        remove_html_tags(&p["body_html"], Some(5000)),
                    );
                    add(&mut n, "g:link", link);
                    add(&mut n, "g:image_link", image);
                    add(
                        &mut n,
                        "g:availability",
                        if available {
                            "in stock"
                        } else {
                            "out of stock"
                        },
                    );
                    add(
                        &mut n,
                        "g:price",
                        format_price(
                            v.get("price").unwrap_or(&Value::String("0.0".into())),
                            currency,
                        ),
                    );
                    add(&mut n, "g:brand", get(p, "vendor", ""));
                    add(&mut n, "g:condition", "new");
                    let tags = &p["tags"];
                    let category = if let Some(tags) = tags.as_array() {
                        tags.iter()
                            .map(|t| t.as_str().ok_or("Non-string tag"))
                            .collect::<std::result::Result<Vec<_>, _>>()?
                            .join(", ")
                    } else if truth(tags) {
                        text(tags)
                    } else {
                        "Home & Garden".into()
                    };
                    add(&mut n, "g:google_product_category", category);
                    // A SKU is not a GTIN; Merchant Center rejects invalid ones.
                    if truth(&v["barcode"]) {
                        add(&mut n, "g:gtin", text(&v["barcode"]));
                    }
                    if truth(&v["sku"]) {
                        add(&mut n, "g:mpn", text(&v["sku"]));
                    }
                    if truth(&p["product_type"]) {
                        add(&mut n, "g:product_type", text(&p["product_type"]));
                    }
                    for img in imgs.iter().skip(1).filter(|s| !s.is_empty()) {
                        add(&mut n, "g:additional_image_link", img.clone());
                    }
                    Ok(Node::branch("item", n))
                }
                FeedType::Bing => {
                    for (k, val) in [
                        ("ProductID", id),
                        ("Title", product_title),
                        ("Link", link),
                        ("ImageLink", image),
                        ("Price", format!("{} {currency}", integer(&v["price"])?)),
                        ("Brand", get(p, "vendor", "")),
                        ("MPN", get(v, "sku", "")),
                        (
                            "Availability",
                            if available {
                                "In Stock".into()
                            } else {
                                "Out of Stock".into()
                            },
                        ),
                        ("Condition", "New".into()),
                        ("Description", remove_html_tags(&p["body_html"], None)),
                        ("ProductType", get(p, "product_type", "")),
                        ("ItemGroupID", required(p, "id")?),
                    ] {
                        add(&mut n, k, val);
                    }
                    if truth(&v["compare_at_price"]) {
                        add(
                            &mut n,
                            "SalePrice",
                            format!("{} {currency}", integer(&v["compare_at_price"])?),
                        );
                    }
                    if truth(&v["grams"]) {
                        add(
                            &mut n,
                            "ShippingWeight",
                            format!(
                                "{} kg",
                                fixed(number(&v["grams"]).ok_or("Invalid weight")? / 1000.0, 2)
                            ),
                        );
                    }
                    for img in imgs.iter().skip(1) {
                        add(&mut n, "AdditionalImageLink", img.clone());
                    }
                    n.push(Node::branch(
                        "Shipping",
                        vec![
                            Node::leaf("Service", "PPL"),
                            Node::leaf("Country", "CZ"),
                            Node::leaf("Price", format!("0 {currency}")),
                        ],
                    ));
                    if truth(&v["barcode"]) {
                        add(&mut n, "GTIN", text(&v["barcode"]));
                    }
                    Ok(Node::branch("Product", n))
                }
                FeedType::Zbozi => {
                    let tags = match &p["tags"] {
                        Value::Array(a) => a
                            .iter()
                            .map(|v| v.as_str().ok_or("Non-string tag"))
                            .collect::<std::result::Result<Vec<_>, _>>()?
                            .join(" | "),
                        Value::String(s) => s
                            .chars()
                            .map(|c| c.to_string())
                            .collect::<Vec<_>>()
                            .join(" | "),
                        Value::Null if p.get("tags").is_none() => String::new(),
                        _ => return Err("Invalid tags".into()),
                    };
                    if p.get("product_type").is_some_and(|v| !v.is_string()) {
                        return Err("Invalid product_type: expected a string".into());
                    }
                    let typ = get(p, "product_type", "");
                    let sku = if truth(&v["sku"]) {
                        text(&v["sku"])
                    } else {
                        format!(
                            "MM-{}",
                            handle.chars().take(10).collect::<String>().to_uppercase()
                        )
                    };
                    for (k, val) in [
                        ("PRODUCTNAME", product_title.clone()),
                        ("DESCRIPTION", remove_html_tags(&p["body_html"], None)),
                        ("URL", link),
                        ("PRICE_VAT", integer(&v["price"])?),
                        ("DELIVERY_DATE", "3".into()),
                        ("IMGURL", image),
                        ("ITEM_ID", id),
                        ("ITEMGROUP_ID", required(p, "id")?),
                        ("PRODUCT", required(p, "title")?),
                        ("MANUFACTURER", get(p, "vendor", "")),
                        (
                            "CATEGORYTEXT",
                            typ.split('/').collect::<Vec<_>>().join(" | "),
                        ),
                        ("EAN", get(v, "barcode", "")),
                        ("PRODUCTNO", sku),
                        ("CONDITION", "new".into()),
                        ("BRAND", get(p, "vendor", "")),
                        ("WARRANTY", "24".into()),
                        ("VISIBILITY", "1".into()),
                        ("CUSTOM_LABEL_0", "Shopify".into()),
                        ("CUSTOM_LABEL_1", typ),
                        ("CUSTOM_LABEL_2", tags),
                    ] {
                        add(&mut n, k, val);
                    }
                    if truth(&v["compare_at_price"]) {
                        add(
                            &mut n,
                            "PRICE_BEFORE_DISCOUNT",
                            integer(&v["compare_at_price"])?,
                        );
                    }
                    for img in imgs.iter().skip(1) {
                        add(&mut n, "IMGURL_ALTERNATIVE", img.clone());
                    }
                    for service in ["ZASILKOVNA", "PPL"] {
                        n.push(Node::branch(
                            "DELIVERY",
                            vec![
                                Node::leaf("DELIVERY_ID", service),
                                Node::leaf("DELIVERY_PRICE", "59"),
                                Node::leaf("DELIVERY_PRICE_COD", "0"),
                            ],
                        ));
                    }
                    let mut param = |name: String, val: String| {
                        n.push(Node::branch(
                            "PARAM",
                            vec![Node::leaf("PARAM_NAME", name), Node::leaf("VAL", val)],
                        ))
                    };
                    for i in 0..3 {
                        let key = format!("option{}", i + 1);
                        if truth(&v[&key]) {
                            let fallback = if i == 0 {
                                "Variant".into()
                            } else {
                                format!("Variant {}", i + 1)
                            };
                            let name = p["options"]
                                .as_array()
                                .and_then(|a| a.get(i))
                                .map(|v| required(v, "name"))
                                .transpose()?
                                .unwrap_or(fallback);
                            param(name, text(&v[&key]));
                        }
                    }
                    if truth(&v["grams"]) {
                        param(
                            "Hmotnost".into(),
                            format!(
                                "{} kg",
                                fixed(number(&v["grams"]).ok_or("Invalid weight")? / 1000.0, 2)
                            ),
                        );
                    }
                    if !v["available"].is_null() {
                        param(
                            "Dostupnost".into(),
                            if available {
                                "Skladem".into()
                            } else {
                                "Není skladem".into()
                            },
                        );
                    }
                    static POT: LazyLock<Regex> =
                        LazyLock::new(|| Regex::new(r"(\d+)\s*cm").unwrap());
                    if let Some(c) = POT.captures(&product_title) {
                        param("Průměr květináče".into(), format!("{} cm", &c[1]));
                    }
                    Ok(Node::branch("SHOPITEM", n))
                }
            }
        })();
        match mapped {
            Ok(node) => result.push(node),
            Err(e) if kind == FeedType::Google => log(
                "ERROR",
                format!("Error processing variant {}: {e}", get(v, "id", "unknown")),
            ),
            Err(e) => return Err(e),
        }
    }
    Ok(result)
}
#[derive(Debug)]
pub struct EmptyFeedError {
    pub store_url: String,
}
impl std::fmt::Display for EmptyFeedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f,"No products collected from {}. Refusing to write an empty feed, because uploading one delists the whole catalogue.",self.store_url)
    }
}
impl std::error::Error for EmptyFeedError {}
pub fn require_products(store: &str, products: &[Node]) -> Result<()> {
    if products.is_empty() {
        return Err(Box::new(EmptyFeedError {
            store_url: store.into(),
        }));
    }
    Ok(())
}
pub fn render(kind: FeedType, store: &str, shop: &Value, items: Vec<Node>) -> Result<String> {
    require_products(store, &items)?;
    let name = shop
        .get("name")
        .filter(|v| !v.is_null())
        .map(text)
        .unwrap_or_default();
    let url = get(shop, "url", store);
    let root = match kind {
        FeedType::Google => {
            let mut channel = vec![
                Node::leaf("title", name),
                Node::leaf("link", url),
                Node::leaf("description", get(shop, "description", "")),
            ];
            channel.extend(items);
            let mut root = Node::branch("rss", vec![Node::branch("channel", channel)]);
            root.attributes = vec![
                ("version".into(), "2.0".into()),
                ("xmlns:g".into(), "http://base.google.com/ns/1.0".into()),
            ];
            root
        }
        FeedType::Bing => {
            let mut nodes = vec![
                Node::leaf("Title", name),
                Node::leaf("Description", ""),
                Node::leaf("Link", url),
            ];
            nodes.extend(items);
            Node::branch("Catalog", nodes)
        }
        FeedType::Zbozi => {
            let mut nodes = vec![
                Node::leaf("SHOP_NAME", name),
                Node::leaf("SHOP_DESCRIPTION", ""),
                Node::leaf("SHOP_URL", url),
            ];
            nodes.extend(items);
            Node::branch("SHOP", nodes)
        }
    };
    let mut out = "<?xml version='1.0' encoding='utf-8'?>\n".to_string();
    root.xml(&mut out);
    Ok(out)
}
pub fn publish(path: &Path, data: &[u8]) -> Result<()> {
    let parent = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    std::fs::create_dir_all(parent)?;
    let mut builder = tempfile::Builder::new();
    builder.prefix(".feed-");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        builder.permissions(std::fs::Permissions::from_mode(0o666));
    }
    let mut file = builder.tempfile_in(parent)?;
    if let Ok(metadata) = std::fs::metadata(path) {
        file.as_file().set_permissions(metadata.permissions())?;
    }
    file.write_all(data)?;
    file.flush()?;
    file.persist(path)?;
    Ok(())
}
pub fn generate<T: Transport>(
    client: &ShopifyClient<T>,
    kind: FeedType,
    output: &Path,
    currency: &str,
    download_images: bool,
    max_workers: usize,
) -> Result<()> {
    let label = kind.label();
    let store = &client.store_url;
    log(
        "INFO",
        format!("Starting {label} feed generation for {store}"),
    );
    client.failed.store(false, Ordering::Relaxed);
    let result = (|| -> Result<()> {
        let mut items = vec![];
        if kind == FeedType::Bing {
            for p in client.products(None) {
                items.extend(process_product(kind, store, currency, &p)?);
            }
        } else {
            // A product listed in several collections must appear once.
            let mut seen = HashSet::new();
            for c in client.collections() {
                let h = required(&c, "handle")?;
                log(
                    "INFO",
                    format!("Processing collection: {}", required(&c, "title")?),
                );
                for p in client.products(Some(&h)) {
                    if !p["id"].is_null() && !seen.insert(text(&p["id"])) {
                        continue;
                    }
                    match process_product(kind, store, currency, &p) {
                        Ok(v) => items.extend(v),
                        // Skip only the broken product, not the rest of the collection.
                        Err(e) => log(
                            "ERROR",
                            format!(
                                "Error processing product {} in {h}: {e}",
                                get(&p, "id", "unknown")
                            ),
                        ),
                    }
                }
            }
        }
        if client.failed.load(Ordering::Relaxed) {
            return Err("Store requests failed, so the catalogue is incomplete. Refusing to publish a partial feed.".into());
        }
        log(
            "INFO",
            format!("Processed {} product variants", items.len()),
        );
        require_products(store, &items)?;
        if kind == FeedType::Google && download_images {
            let host = reqwest::Url::parse(store)?
                .host_str()
                .unwrap_or_default()
                .split('.')
                .next()
                .unwrap_or_default()
                .to_string();
            let folder = output.parent().unwrap_or(Path::new(".")).join(format!(
                "{host}_images_{}",
                chrono::Local::now().format("%Y%m%d_%H%M%S")
            ));
            log(
                "INFO",
                format!("Starting image download to folder: {}", folder.display()),
            );
            let urls = items
                .iter()
                .flat_map(|n| &n.children)
                .filter(|n| n.name == "g:image_link" || n.name == "g:additional_image_link")
                .map(|n| n.text.clone())
                .collect::<Vec<_>>();
            crate::images::download_product_images(&urls, &folder, max_workers)?;
        }
        let count = items.len();
        let xml = render(kind, store, &client.shop_info(), items)?;
        publish(output, xml.as_bytes())?;
        log(
            "INFO",
            format!("{label} feed saved to {}", output.display()),
        );
        log(
            "INFO",
            format!("Feed generation completed: {count} products"),
        );
        Ok(())
    })();
    if result.is_err() {
        log("ERROR", format!("Error generating {label} feed"));
    }
    result
}

pub struct GoogleFeedGenerator {
    pub client: ShopifyClient,
    pub currency: String,
    pub download_images: bool,
    pub max_workers: usize,
}
impl GoogleFeedGenerator {
    pub fn new(store_url: &str) -> Self {
        Self {
            client: ShopifyClient::new(store_url),
            currency: "CZK".into(),
            download_images: false,
            max_workers: 4,
        }
    }
    pub fn get_feed_type(&self) -> &'static str {
        "google"
    }
    pub fn generate<P: AsRef<Path>>(&self, output: P) -> Result<std::path::PathBuf> {
        generate(
            &self.client,
            FeedType::Google,
            output.as_ref(),
            &self.currency,
            self.download_images,
            self.max_workers,
        )?;
        Ok(output.as_ref().into())
    }
}
pub struct BingFeedGenerator {
    pub client: ShopifyClient,
    pub currency: String,
}
impl BingFeedGenerator {
    pub fn new(store_url: &str) -> Self {
        Self {
            client: ShopifyClient::new(store_url),
            currency: "CZK".into(),
        }
    }
    pub fn get_feed_type(&self) -> &'static str {
        "bing"
    }
    pub fn generate<P: AsRef<Path>>(&self, output: P) -> Result<std::path::PathBuf> {
        generate(
            &self.client,
            FeedType::Bing,
            output.as_ref(),
            &self.currency,
            false,
            4,
        )?;
        Ok(output.as_ref().into())
    }
}
pub struct ZboziFeedGenerator {
    pub client: ShopifyClient,
}
impl ZboziFeedGenerator {
    pub fn new(store_url: &str) -> Self {
        Self {
            client: ShopifyClient::new(store_url),
        }
    }
    pub fn get_feed_type(&self) -> &'static str {
        "zbozi"
    }
    pub fn generate<P: AsRef<Path>>(&self, output: P) -> Result<std::path::PathBuf> {
        generate(
            &self.client,
            FeedType::Zbozi,
            output.as_ref(),
            "CZK",
            false,
            4,
        )?;
        Ok(output.as_ref().into())
    }
}
