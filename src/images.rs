// Project: shopify-to-feeds
// File: src/images.rs
// Description: Bounded concurrent image downloads with collision-safe names.
// Author: Jan Alexandr Kopřiva
// Based on shopify-to-feeds by Jan Alexandr Kopřiva
// License: MIT

use crate::{log, security, Result};
use std::{
    collections::{BTreeSet, HashMap},
    path::Path,
    sync::{
        atomic::{AtomicUsize, Ordering},
        Mutex,
    },
};
pub const IMAGE_USER_AGENT: &str = "python-requests/2.33.0";
pub fn image_filename(url: &str) -> String {
    let base = reqwest::Url::parse(url)
        .ok()
        .and_then(|u| {
            u.path_segments()
                .and_then(|mut p| p.next_back())
                .map(str::to_string)
        })
        .unwrap_or_default();
    if base.is_empty() || base == "." || base == ".." || base.contains(['\\', ':']) {
        format!("image_{:x}.jpg", md5::compute(url))
    } else {
        base
    }
}
pub trait ImageTransport: Sync {
    fn get(&self, url: &str) -> Result<Vec<u8>>;
}
pub struct HttpImages;
impl ImageTransport for HttpImages {
    fn get(&self, url: &str) -> Result<Vec<u8>> {
        let (_, parsed, addrs) = security::validate(url, true)?;
        let client = crate::client::http_client_builder()
            .resolve_to_addrs(parsed.host_str().ok_or("Image URL has no host.")?, &addrs)
            .build()?;
        let mut response = client
            .get(parsed)
            .header("User-Agent", IMAGE_USER_AGENT)
            .header("Accept", "*/*")
            .header("Connection", "keep-alive")
            .send()?
            .error_for_status()?;
        let mut bytes = Vec::new();
        std::io::Read::read_to_end(&mut response, &mut bytes)?;
        Ok(bytes)
    }
}
pub fn download_image(url: &str, folder: &Path, filename: &str) -> Result<()> {
    download_image_with(&HttpImages, url, folder, filename)
}
pub fn download_image_with<T: ImageTransport>(
    transport: &T,
    url: &str,
    folder: &Path,
    filename: &str,
) -> Result<()> {
    if filename.is_empty()
        || filename == "."
        || filename == ".."
        || filename.contains(['/', '\\', ':'])
    {
        return Err("Invalid image filename".into());
    }
    let bytes = transport.get(url)?;
    crate::feeds::publish(&folder.join(filename), &bytes)
}
pub fn download_product_images(
    urls: &[String],
    folder: &Path,
    workers: usize,
) -> Result<HashMap<String, String>> {
    download_product_images_with(&HttpImages, urls, folder, workers)
}
pub fn download_product_images_with<T: ImageTransport>(
    transport: &T,
    urls: &[String],
    folder: &Path,
    workers: usize,
) -> Result<HashMap<String, String>> {
    if workers == 0 {
        return Err("max_workers must be greater than 0".into());
    }
    if !folder.exists() {
        std::fs::create_dir_all(folder)?;
        log(
            "INFO",
            format!("Created images folder: {}", folder.display()),
        );
    }
    let urls: Vec<_> = urls
        .iter()
        .filter(|u| !u.is_empty())
        .cloned()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    log(
        "INFO",
        format!("Found {} unique images to download", urls.len()),
    );
    if urls.is_empty() {
        log("INFO", "No images found to download");
        return Ok(HashMap::new());
    }
    let names: Vec<_> = urls
        .iter()
        .map(|u| {
            let base = image_filename(u);
            if urls
                .iter()
                .filter(|other| image_filename(other) == base)
                .count()
                > 1
            {
                format!("{:x}_{base}", md5::compute(u))
            } else {
                base
            }
        })
        .collect();
    let index = AtomicUsize::new(0);
    let finished = AtomicUsize::new(0);
    let result = Mutex::new(HashMap::new());
    std::thread::scope(|scope| {
        for _ in 0..workers.min(urls.len()) {
            scope.spawn(|| loop {
                let i = index.fetch_add(1, Ordering::Relaxed);
                if i >= urls.len() {
                    break;
                }
                match download_image_with(transport, &urls[i], folder, &names[i]) {
                    Ok(()) => {
                        result
                            .lock()
                            .unwrap()
                            .insert(urls[i].clone(), names[i].clone());
                    }
                    Err(e) => log(
                        "ERROR",
                        format!("Error downloading image from {}: {e}", urls[i]),
                    ),
                }
                let done = finished.fetch_add(1, Ordering::Relaxed) + 1;
                if done.is_multiple_of(10) || done == urls.len() {
                    log("INFO", format!("Downloaded {done}/{} images", urls.len()));
                }
            });
        }
    });
    let result = result.into_inner().unwrap();
    log(
        "INFO",
        format!(
            "Image download completed. Downloaded {} images",
            result.len()
        ),
    );
    Ok(result)
}

pub struct ImageDownloader {
    pub max_workers: usize,
}
impl Default for ImageDownloader {
    fn default() -> Self {
        Self { max_workers: 4 }
    }
}
impl ImageDownloader {
    pub fn new(max_workers: usize) -> Self {
        Self { max_workers }
    }
    pub fn download_image(&self, url: &str, folder: &Path) -> Option<String> {
        if url.is_empty() {
            return None;
        }
        if let Err(e) = security::validate(url, true) {
            log("WARNING", format!("Rejected image URL {url:?}: {e}"));
            return None;
        }
        let filename = image_filename(url);
        match download_image(url, folder, &filename) {
            Ok(()) => Some(filename),
            Err(e) => {
                log("ERROR", format!("Error downloading image from {url}: {e}"));
                None
            }
        }
    }
    pub fn download_product_images(
        &self,
        products: &[serde_json::Value],
        folder: &Path,
        image_field: &str,
    ) -> Result<HashMap<String, String>> {
        let mut urls = Vec::new();
        for product in products {
            if let Some(url) = product[image_field].as_str().filter(|s| !s.is_empty()) {
                urls.push(url.to_string());
            }
            if let Some(extra) = product["additional_image_link"].as_array() {
                urls.extend(extra.iter().filter_map(|v| v.as_str()).map(str::to_string));
            }
        }
        download_product_images(&urls, folder, self.max_workers)
    }
}
