# Shopify to Feeds

Generuje produktové XML feedy z Shopify obchodů pro Google Merchant Center, Bing Shopping a Zbozi.cz. Nástroj automaticky stahuje produkty z Shopify API a vytváří validní XML soubory připravené k nahrání do e-commerce platforem.

## Popis

Shopify to Feeds je Python balíček pro generování produktových feedů ve formátu XML. Podporuje tři hlavní platformy: Google Merchant Center, Bing Shopping a Zbozi.cz. Aplikace poskytuje jak Python API pro přímé použití v kódu, tak REST API server pro vzdálené generování feedů.

## Instalace

```bash
pip install -r requirements.txt
```

Nebo jako balíček:

```bash
pip install -e .
```

## Použití

### Python API

```python
from shopify_to_feeds.feeds import GoogleFeedGenerator, BingFeedGenerator, ZboziFeedGenerator

# Google Merchant Center
generator = GoogleFeedGenerator("https://example.myshopify.com")
generator.generate("google_feed.xml")

# Bing Shopping
generator = BingFeedGenerator("https://example.myshopify.com")
generator.generate("bing_feed.xml")

# Zbozi.cz
generator = ZboziFeedGenerator("https://example.myshopify.com")
generator.generate("zbozi_feed.xml")
```

### REST API Server

```bash
python -m shopify_to_feeds.api
```

Nebo pomocí uvicorn:

```bash
uvicorn shopify_to_feeds.api:app --host 0.0.0.0 --port 8000
```

Generování feedu přes API:

```bash
curl -X POST "http://localhost:8000/feed/update/https://example.myshopify.com?feed_type=google"
```

Odpověď:

```json
{
  "message": "Feed update started",
  "store_url": "https://example.myshopify.com",
  "feed_type": "google",
  "feed_url": "/feeds/ed003536_google.xml"
}
```

## Licence

MIT License - viz [LICENSE](LICENSE) soubor.

