// Project: shopify-to-feeds
// File: src/bin/smoke.rs
// Description: Manual live-store smoke run for all three feed formats.
// Author: Jan Alexandr Kopřiva
// License: AGPL-3.0-or-later
use clap::Parser;
use shopify_to_feeds::{
    client::ShopifyClient,
    feeds::{generate, FeedType},
    log,
};
use std::path::PathBuf;
#[derive(Parser)]
#[command(about = "Build every feed against a real store and report what came out.")]
struct Args {
    #[arg(help = "Shopify store URL, for example https://shop.example.com")]
    store_url: String,
    #[arg(
        short = 'o',
        long,
        default_value = "smoke_feeds_out",
        help = "Where to write the feeds"
    )]
    output_dir: PathBuf,
}
fn main() -> std::process::ExitCode {
    let args = Args::parse();
    if let Err(e) = std::fs::create_dir_all(&args.output_dir) {
        log("ERROR", e.to_string());
        return std::process::ExitCode::FAILURE;
    }
    let mut failed = vec![];
    for kind in [FeedType::Google, FeedType::Bing, FeedType::Zbozi] {
        let name = kind.name();
        log("INFO", "=".repeat(60));
        log("INFO", format!("Building the {name} feed"));
        let output = args.output_dir.join(format!("{name}_feed.xml"));
        match generate(
            &ShopifyClient::new(&args.store_url),
            kind,
            &output,
            "CZK",
            false,
            4,
        ) {
            Ok(()) => {
                let size = std::fs::metadata(&output).map(|m| m.len()).unwrap_or(0);
                log(
                    "INFO",
                    format!("{name} feed: {} ({} bytes)", output.display(), commas(size)),
                );
            }
            Err(e) => {
                log("ERROR", format!("{name} feed: {e}"));
                failed.push(name);
            }
        }
    }
    log("INFO", "=".repeat(60));
    for name in ["google", "bing", "zbozi"] {
        log(
            "INFO",
            format!(
                "{name:<8} {}",
                if failed.contains(&name) {
                    "failed"
                } else {
                    "built"
                }
            ),
        );
    }
    if failed.is_empty() {
        log("INFO", "All 3 feeds built");
        std::process::ExitCode::SUCCESS
    } else {
        log(
            "ERROR",
            format!("{} of 3 feeds failed: {}", failed.len(), failed.join(", ")),
        );
        std::process::ExitCode::FAILURE
    }
}
fn commas(n: u64) -> String {
    let s = n.to_string();
    s.chars()
        .enumerate()
        .fold(String::new(), |mut out, (i, c)| {
            if i > 0 && (s.len() - i).is_multiple_of(3) {
                out.push(',');
            }
            out.push(c);
            out
        })
}
