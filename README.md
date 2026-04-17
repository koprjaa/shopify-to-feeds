# shopify-to-feeds

**Generates Google Merchant Center / Bing Shopping / Zboží.cz XML product feeds from any Shopify store — usable as a Python library or a FastAPI microservice.**

![python](https://img.shields.io/badge/python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![license](https://img.shields.io/badge/license-MIT-A31F34?style=flat-square)
![status](https://img.shields.io/badge/status-active-22863A?style=flat-square)
![fastapi](https://img.shields.io/badge/FastAPI-0.104-009688?style=flat-square&logo=fastapi&logoColor=white)
![pydantic](https://img.shields.io/badge/pydantic-2.5-E92063?style=flat-square&logo=pydantic&logoColor=white)
![lxml](https://img.shields.io/badge/lxml-4.9-555?style=flat-square)

Shopify's native feed exports only support Google Merchant Center and charge for the rest. This does all three for free, against any Shopify store's public `/products.json` endpoint.

## Three feeds, one codebase

```
shopify_to_feeds/
├── feeds/
│   ├── base.py       # abstract FeedGenerator
│   ├── google.py     # Google Merchant Center XML
│   ├── bing.py       # Bing Shopping XML
│   └── zbozi.py      # Zboží.cz XML (Czech comparison shopping)
└── api.py            # FastAPI server with background tasks
```

Each generator subclasses `FeedGenerator`, overrides the field-mapping methods, and inherits pagination, retry, and image handling for free.

## As a library

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

## As a service

```bash
uv venv
uv pip install -r requirements.txt
uvicorn shopify_to_feeds.api:app --host 0.0.0.0 --port 8000
```

Fire-and-forget feed generation (background task, caches to `static/feeds/`):

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

The short hash in the filename is a hash of the store URL, so calling the endpoint repeatedly for the same store overwrites the same cached file — point Google Merchant Center at that stable URL and it always gets the latest export.

## Supported feed formats

| feed | platform | key fields |
|------|----------|-----------|
| `google` | Google Merchant Center | `g:id`, `g:price`, `g:availability`, `g:condition`, `g:brand`, `g:shipping` |
| `bing` | Bing Shopping | same field model as Google with namespace tweaks |
| `zbozi` | Zboží.cz | `SHOP`, `SHOPITEM` schema with `ITEM_TYPE`, `DELIVERY_DATE` |

## Known limits

- No OAuth — we hit the public `/products.json` endpoint, so metafields and private fields aren't available. For those, plug in Shopify Admin API with an access token.
- `uwsgi` is listed in `requirements.txt` (Linux-only) for production deployment. On Windows / macOS dev, the marker `; sys_platform != "win32"` skips it automatically.

## License

[MIT](LICENSE)
