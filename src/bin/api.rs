// Project: shopify-to-feeds
// File: src/bin/api.rs
// Description: Runnable HTTP service entry point.
// Author: Jan Alexandr Kopřiva
// Based on shopify-to-feeds by Jan Alexandr Kopřiva
// License: MIT

use clap::Parser;
use shopify_to_feeds::{
    api::{self, AppState},
    Result,
};
#[derive(Parser)]
#[command(about = "Shopify to Feeds API", version)]
struct Args {
    #[arg(long, env = "HOST", default_value = "127.0.0.1")]
    host: String,
    #[arg(long, env = "PORT", default_value_t = 8000)]
    port: u16,
}
#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    let state = AppState::from_env()?;
    let listener = tokio::net::TcpListener::bind((args.host.as_str(), args.port)).await?;
    axum::serve(listener, api::router(state)).await?;
    Ok(())
}
