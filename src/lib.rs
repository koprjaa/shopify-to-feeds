// Project: shopify-to-feeds
// File: src/lib.rs
// Description: Public feed generation library and shared logging.
// Author: Jan Alexandr Kopřiva
// Based on shopify-to-feeds by Jan Alexandr Kopřiva
// License: MIT

pub mod api;
pub mod client;
pub mod feeds;
pub mod helpers;
pub mod images;
pub mod security;

pub type Error = Box<dyn std::error::Error + Send + Sync>;
pub type Result<T> = std::result::Result<T, Error>;

pub fn log(level: &str, message: impl AsRef<str>) {
    eprintln!(
        "{} - {} - {}",
        chrono::Local::now().format("%Y-%m-%d %H:%M:%S,%3f"),
        level,
        message.as_ref()
    );
}

pub use feeds::{BingFeedGenerator, GoogleFeedGenerator, ZboziFeedGenerator};
