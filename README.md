# shopify-to-feeds

Generates Google Merchant Center, Bing Shopping, and Zboží.cz product feeds from any Shopify store. It works as a Python library and as a FastAPI service.

![python](https://img.shields.io/badge/python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![license](https://img.shields.io/badge/license-MIT-A31F34?style=flat-square)
![status](https://img.shields.io/badge/status-active-22863A?style=flat-square)
[![ci](https://github.com/koprjaa/shopify-to-feeds/actions/workflows/ci.yml/badge.svg)](https://github.com/koprjaa/shopify-to-feeds/actions/workflows/ci.yml)

The native Shopify export covers Google Merchant Center and charges for the other formats. This tool produces all three from the public `/products.json` endpoint.

## Install

```bash
uv venv
uv pip install -r requirements.txt
```

## Use

As a library:

```python
from shopify_to_feeds.feeds import (
    GoogleFeedGenerator,
    BingFeedGenerator,
    ZboziFeedGenerator,
)

GoogleFeedGenerator("https://example.myshopify.com").generate("google_feed.xml")
BingFeedGenerator("https://example.myshopify.com").generate("bing_feed.xml")
ZboziFeedGenerator("https://example.myshopify.com").generate("zbozi_feed.xml")
```

As a service:

```bash
uvicorn shopify_to_feeds.api:app --host 0.0.0.0 --port 8000
```

The update endpoint starts a background task and caches the result under `static/feeds/`:

```bash
curl -X POST "http://localhost:8000/feed/update/https://example.myshopify.com?feed_type=google"
```

```json
{
  "message": "Feed update started",
  "store_url": "https://example.myshopify.com",
  "feed_type": "google",
  "feed_url": "/feeds/ed003536_google.xml"
}
```

The hash in the filename comes from the store URL. Repeated calls for the same store overwrite the same file. Point Google Merchant Center at that stable URL and it always reads the current export.

## Feed formats

| Feed | Platform | Main fields |
|---|---|---|
| `google` | Google Merchant Center | `g:id`, `g:price`, `g:availability`, `g:condition`, `g:brand`, `g:shipping` |
| `bing` | Bing Shopping | Same field model as Google, with different namespaces. |
| `zbozi` | Zboží.cz | `SHOP` and `SHOPITEM` schema with `ITEM_TYPE` and `DELIVERY_DATE`. |

## How it works

```
shopify_to_feeds/
  feeds/base.py     Abstract FeedGenerator
  feeds/google.py   Google Merchant Center XML
  feeds/bing.py     Bing Shopping XML
  feeds/zbozi.py    Zboží.cz XML
  api.py            FastAPI server with background tasks
```

Each generator subclasses `FeedGenerator` and overrides the field mapping. Pagination, retry, and image handling come from the base class.

## Limits

- There is no OAuth step, so the public endpoint exposes no metafields and no private fields. Those need the Shopify Admin API with an access token.
- `requirements.txt` lists `uwsgi` for production on Linux. The marker `; sys_platform != "win32"` skips it on Windows and macOS.
- The repository history contains a large export of scraped product images from three real stores. Clone with `--depth 1` if you only want the code.
- `test_feeds.py` is a script that generates all three feeds against a live store and prints a report. It is a smoke run, not a test.

## Development

```bash
uv run --extra dev ruff check .
uv run --extra dev pytest -q
```

The suite covers the value formatting every generator shares: description
cleaning, price format and the gram to kilogram conversion. A wrong value there
reaches all three merchant centres, and each rejects a feed rather than
explaining it. CI runs on Python 3.10, 3.11, and 3.12, across Linux and Windows.

## License

[MIT](LICENSE)
