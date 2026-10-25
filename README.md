# shopify-to-feeds

Generates Google, Bing and Zbozi.cz product feeds from a Shopify store.

[![CI](https://github.com/koprjaa/shopify-to-feeds/actions/workflows/ci.yml/badge.svg)](https://github.com/koprjaa/shopify-to-feeds/actions/workflows/ci.yml)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-A31F34?style=flat-square)](LICENSE)

Export XML for Google Merchant Center, Bing Shopping and Zboží.cz through an HTTP service or a command that writes all three formats. A Rust library is also available.

Stores must expose public Shopify JSON endpoints over HTTPS. Google and Zboží.cz read products through collections; Bing reads all products. Google and Bing prices default to CZK.

## Install

With a stable Rust toolchain installed, run from the repository directory:

```sh
cargo install --path .
```

This installs `shopify-feeds-api` and `smoke_feeds`. Ensure Cargo's binary directory is on your `PATH`.

## Use

Set `FEED_API_KEY` in your shell environment before starting the service:

```sh
shopify-feeds-api
```

It listens on `127.0.0.1:8000`. Use `--host` and `--port` to change the address, or `--help` for available options. Add custom store domains to the comma-separated `FEED_ALLOWED_HOSTS` environment variable; `myshopify.com` subdomains are already allowed.

Replace the example URL with your store:

```sh
curl -X POST -H "X-API-Key: $FEED_API_KEY" \
  'http://localhost:8000/feed/update/https://example.myshopify.com?feed_type=google&download_images=false'
```

Generation runs in the background. Poll `GET /feed/status/https://example.myshopify.com` with the same header, then fetch the returned `feed_url` without authentication. Files are stored in `static/feeds/`, relative to the working directory. See `/docs` for other formats and image-download options.

To export all formats without starting the service or downloading images:

```sh
smoke_feeds https://example.myshopify.com --output-dir exports
```

This writes `google_feed.xml`, `bing_feed.xml` and `zbozi_feed.xml`. Without `--output-dir`, output goes to `smoke_feeds_out`.

## License

[AGPL-3.0-or-later](LICENSE)
