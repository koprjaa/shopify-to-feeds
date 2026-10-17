# shopify-to-feeds

Generate Google Merchant Center, Bing Shopping and Zboží.cz XML product feeds from a Shopify store's public JSON endpoints. This repository provides a Rust library, an HTTP service and a manual smoke-run command.

![rust](https://img.shields.io/badge/rust-stable-DEA584?style=flat-square&logo=rust&logoColor=black)
![license](https://img.shields.io/badge/license-MIT-A31F34?style=flat-square)
[![ci](https://github.com/koprjaa/shopify-to-feeds/actions/workflows/ci.yml/badge.svg)](https://github.com/koprjaa/shopify-to-feeds/actions/workflows/ci.yml)


## Install

Install the current stable Rust toolchain, then run:

```sh
cargo install --path .
```

This installs `shopify-feeds-api` and `smoke_feeds`. No Python interpreter or external application server is required.

## Use

Start the service:

```sh
shopify-feeds-api --host 0.0.0.0 --port 8000
```

Set `FEED_API_KEY` in the deployment environment and add custom store domains to `FEED_ALLOWED_HOSTS`. Keep real credentials out of source files. The following command reads the key from the shell environment:

```sh
curl -X POST -H "X-API-Key: $FEED_API_KEY" \
  'http://localhost:8000/feed/update/https://example.myshopify.com?feed_type=google&download_images=true'
```

The response contains `message`, normalized `store_url`, `feed_type`, `feed_url` and `download_images`. Poll `GET /feed/status/https://example.myshopify.com` with the same header. The public `GET /feeds/{filename}` route serves the result as `application/xml`; feed files remain under `static/feeds/`. The filename is the first eight hexadecimal characters of the MD5 of the normalized store URL, followed by `_google.xml`, `_bing.xml` or `_zbozi.xml`. Repeated updates replace the same file.

`GET /` returns service information. Interactive API documentation is available at `/docs` and `/redoc`, with its schema at `/openapi.json`. Documentation viewers load their usual external JavaScript assets when opened in a browser.

A manual smoke run builds all three formats, without image downloads:

```sh
smoke_feeds https://example.myshopify.com
smoke_feeds https://example.myshopify.com -o exports
smoke_feeds https://example.myshopify.com --output-dir exports
```

The output directory defaults to `smoke_feeds_out`. Files are `google_feed.xml`, `bing_feed.xml` and `zbozi_feed.xml`. Exit codes are 0 when every feed succeeds, 1 when any feed fails, and 2 for invalid arguments. This command contacts the specified store and is deliberately excluded from automated tests.

As a library, add this package as a path dependency and use:

```rust,no_run
use shopify_to_feeds::{GoogleFeedGenerator, BingFeedGenerator, ZboziFeedGenerator};

fn main() -> shopify_to_feeds::Result<()> {
    GoogleFeedGenerator::new("https://example.myshopify.com")
        .generate("google_feed.xml")?;
    BingFeedGenerator::new("https://example.myshopify.com")
        .generate("bing_feed.xml")?;
    ZboziFeedGenerator::new("https://example.myshopify.com")
        .generate("zbozi_feed.xml")?;
    Ok(())
}
```

Google defaults to `currency = "CZK"`, `download_images = false`, `max_workers = 4`; Bing defaults to CZK. Configure these public fields before calling `generate`. The shared `feeds::generate` function accepts an injectable `ShopifyClient<T>` for offline integrations. Product pagination is lazy. `images::ImageDownloader` provides single-image and product-image helpers. These are synchronous library operations; async applications should call them from a blocking worker.

## Configuration

| Environment variable | Default | Meaning |
|---|---|---|
| `HOST` | `127.0.0.1` | HTTP bind address; `--host` overrides it. |
| `PORT` | `8000` | HTTP port; `--port` overrides it. |
| `FEED_API_KEY` | unset | Required trimmed key for update/status requests; unset or empty returns 503. |
| `FEED_ALLOWED_HOSTS` | empty | Comma-separated, dot-anchored host suffixes in addition to `myshopify.com`. |
| `FEED_MAX_CONCURRENT` | `4` | Maximum simultaneous background feed jobs; excess jobs record error status. |
| `FEED_STATES_MAX` | `1000` | Maximum in-memory store states. |
| `FEED_STATES_TTL` | `86400` | State lifetime in seconds; eviction runs when a state is inserted. |

State keys are store URLs, shared across feed types, as in the original. Status lookup uses the exact supplied URL. Processing/completed states include a local ISO timestamp, feed URL and image-download flag; error states expose only status and timestamp. States are lost on restart. `DOMAIN` in the example service file remains unused.

Store requests require HTTPS and an allowed host. Images also permit HTTP and Shopify CDN suffixes (`cdn.shopify.com`, `shopify.com`, `shopifycdn.com`). Every resolved address is checked; private, loopback, link-local, multicast, reserved and unspecified destinations are refused. Redirects are not followed. Requests use a 30-second timeout, three total JSON attempts and delays of 5 then 10 seconds. There is no additional rate limit. Image downloads use four workers by default, one attempt each. Feed generation keeps original image URLs even when images are downloaded.

The store User-Agent remains the original Chrome 35 / Mac OS X string. Image requests use `python-requests/2.33.0` for compatibility with the original minimum dependency version; this is an HTTP header, not a runtime dependency. Both use `Accept: */*`, gzip/deflate support and HTTP/1.1 keep-alive.

Deployment examples are in `config/shopify-feed.service` and `config/listnato.conf`. Install the binary at the path used by the service, configure the key through an untracked systemd override, and proxy HTTP to port 8000.

## Feed behavior

| Format | Product source | Preserved behavior |
|---|---|---|
| Google | Every collection's products | Two-decimal prices, description limited to 5000 Unicode characters, SKU as GTIN/MPN, extra images, product links without variant query. |
| Bing | All products, pages of 250 | Integer-truncated prices, compare-at price in `SalePrice`, PPL shipping, optional barcode and two-decimal shipping weight. |
| Zboží.cz | Every collection's products | Integer-truncated prices, delivery date 3, original field order, product options, weight, availability and pot-size parameters. |

Collections are not deduplicated. A product in two collections appears twice in Google/Zboží output. Description cleanup strips tags with the original regular expression and collapses whitespace; it does not decode HTML entities. Existing Czech merchant parameter names/values are retained as feed data. Default Google shipping/tax constants in the original were unused and no shipping/tax elements are added.

XML is UTF-8, with the original declaration, compact layout, field order, escaping and spaced empty elements. An empty catalogue raises `feeds::EmptyFeedError` before any output is created; an existing feed survives a failed run. The project has no CSV, XLSX or non-API JSON export.

## Development

```sh
cargo build --release
cargo test
cargo clippy --all-targets -- -D warnings
cargo fmt --check
```

CI runs the same checks on Ubuntu and Windows. Tests perform no public DNS lookups and never contact live shops. HTTP behavior uses local `httpmock` servers; URL-validation tests inject an offline resolver. No custom TCP test server is needed. Temporary test paths are platform-independent.

Every original helper, security and empty-feed test has an equivalent Rust assertion, including all parameterized cases. Rust's types reject non-string URL arguments at compile time. The old source-introspection guard test is replaced by checking every format's actual write behavior and preservation of existing files. Additional tests cover HTTP contracts, retries, pagination, concurrent state writes, bounded cache eviction, image collisions, CLI exits and byte-exact XML.

`tests/fixtures/product.json` is synthetic. Its XML fixtures were generated with the original Python code before removal: Bing is unchanged; Google has only its duplicate namespace removed; Zboží has its broken parameter elements and missing delivery option corrected. `.gitattributes` disables text conversion for every fixture.

Runtime dependencies are limited to their specific roles:

| Crate | Reason |
|---|---|
| `axum`, `tokio` | HTTP routing, async service runtime and bounded background work. |
| `tower-http` | Portable streaming file responses, HEAD and byte ranges. |
| `reqwest` | HTTP/1.1, rustls, pinned DNS, JSON transport and compression. |
| `serde`, `serde_json` | API/configuration data and Shopify JSON, preserving object insertion order. |
| `regex` | Exact original tag-stripping and pot-size patterns. |
| `chrono` | Original local timestamp and log formats. |
| `md5` | Compatible stable feed filenames and metadata ETags. |
| `tempfile` | Atomic cross-platform publication and safe temporary files. |
| `clap` | CLI parsing, defaults and environment overrides. |

Development-only dependencies are `httpmock` for local HTTP servers and `tower` for in-process HTTP integration tests. XML uses a small ordered serializer so no additional XML dependency is needed.

## Changes from the Python version

1. The implementation and library API are Rust. The three named generators remain available, with typed constructors/public options and `Result` return values. Non-string URLs and other unsupported argument types are compile-time errors; arbitrary Python container representations are not a supported input format. Python packaging, the interpreter-dependent smoke script and the nonfunctional ASGI console entry point are replaced by executable binaries. Smoke arguments/defaults and exit codes are preserved; Clap's help/usage and parse-error wording differ from argparse. The API binary additionally supports `--host`, `--port`, `--help` and `--version`. Negative cache/concurrency configuration values are rejected at startup.
2. Google emits one `xmlns:g` declaration. Python emitted it twice, producing invalid XML. Zboží parameters now contain nested `PARAM_NAME`/`VAL` elements instead of Python dictionary strings. Zboží includes both ZASILKOVNA and PPL deliveries; the original dictionary assignment silently discarded the first carrier.
3. Feed and image files are published by atomic replacement. Readers cannot observe partially written files, and write failures preserve existing output. Existing permissions are copied and new Unix files respect the process umask. Replacement creates a new inode, can change ownership to the writer, and replaces a destination symlink instead of following it.
4. Image URLs sharing a basename receive a deterministic MD5 prefix, preventing overwrites between concurrent workers. Empty/unsafe basenames use `image_<full-MD5>.jpg` instead of a process-random hash modulo 10000. Unsafe Windows filename separators/colon are refused or replaced. Unique URLs are scheduled in sorted order instead of Python set iteration order; completion order remains concurrent. Empty image URLs are filtered before the progress total. Image folders use the parsed hostname rather than a credential-bearing authority.
5. Feed generation, including its blocking HTTP and filesystem work, runs outside the API event loop, so the configured background-job concurrency works while status requests stay responsive. State eviction ties are broken by store URL for deterministic results. Existing store-only status keys and last-completing-job behavior are retained.
6. Validated DNS results are pinned to the outgoing connection, closing the original DNS-rebinding gap. Environment HTTP proxies and Requests-specific CA/netrc settings are not inherited, because they can bypass the validated destination; TLS uses rustls/webpki roots. Deprecated IPv4 relay and IPv6 transition/special-use networks are conservatively rejected. Rust's URL parser also rejects/canonicalizes malformed URLs differently from urllib; normal store paths and Unicode product-link text retain their original behavior. Bare library store hosts now receive HTTPS consistently in both the generator and its client, fixing the original mismatch.
7. Image User-Agent is fixed to the original minimum Requests version (`2.33.0`), rather than varying with the installed Python package. Reqwest controls transport-level header ordering, TLS details and automatic compression. The timeout remains 30 seconds for connection/response operations and streamed body reads; its exact connection/header deadline semantics are those of Reqwest rather than Requests. JSON input must be valid UTF-8 JSON; Python's automatic detection of UTF-16/32 JSON is not reproduced.
8. Authentication handles Unicode header values without Python's `hmac.compare_digest` exception. Local timestamp, log level, progress/success message templates and sanitized API errors remain; backend error details and stack traces use Rust errors instead of Python exceptions. Bulk image URL rejection is reported as a download error; the single-image wrapper retains its rejection warning. There is no Python traceback or external-server access log formatter.
9. The HTTP service is native Axum. uWSGI/uvicorn are no longer used: the service command and nginx example now use HTTP, and obsolete `config/uwsgi.ini` is removed. Root/update/status/file routes, defaults and business error messages remain. Documentation routes are provided through a bundled OpenAPI schema and equivalent viewers; generated operation descriptions, documentation HTML and OAuth redirect markup differ from FastAPI. Invalid boolean query values return 422, with a compact validation detail; other framework-level routing, duplicate/malformed query handling and method-error bodies follow Axum. File responses retain content type, HEAD, ranges, length, modification time and an MD5 metadata ETag; multipart-range framing, conditional-range behavior and transport headers follow tower-http rather than Starlette.

## License

[MIT](LICENSE).
