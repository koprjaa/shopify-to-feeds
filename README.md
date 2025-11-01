# Shopify to Feeds - Universal tool for generating product feeds from Shopify stores

FastAPI aplikace pro generování XML feedů z Shopify obchodů pro různé e-commerce platformy.

## Popis

Tento projekt generuje produktové feedy ve formátu XML pro:
- **Google Merchant Center** (GMC)
- **Bing Shopping**
- **Zbozi.cz**

Aplikace poskytuje REST API endpointy pro automatické generování a aktualizaci feedů z Shopify obchodů.

## Struktura projektu

```
shopify-to-feeds/
├── shopify_to_feeds/          # Hlavní balíček
│   ├── __init__.py
│   ├── api.py                 # FastAPI aplikace
│   ├── feeds/                 # Generátory feedů
│   │   ├── __init__.py
│   │   ├── base.py            # Základní třída pro feedy
│   │   ├── google.py          # Google Merchant Center
│   │   ├── bing.py            # Bing Shopping
│   │   └── zbozi.py           # Zbozi.cz
│   ├── scraper/               # Shopify scraper
│   │   ├── __init__.py
│   │   ├── shopify_client.py  # Shopify API klient
│   │   └── image_downloader.py # Stahování obrázků
│   └── utils/                 # Utility funkce
│       ├── __init__.py
│       └── helpers.py
├── static/                    # Statické soubory
│   └── feeds/                # Generované feedy
├── config/                   # Konfigurace deploymentu
├── setup.py                   # Instalační skript
├── requirements.txt
└── README.md
```

## Instalace

### Instalace jako balíček

```bash
pip install -e .
```

### Instalace závislostí

```bash
pip install -r requirements.txt
```

## Použití

### Spuštění API serveru

```bash
# Přímo
python -m shopify_to_feeds.api

# Nebo pomocí uvicorn
uvicorn shopify_to_feeds.api:app --host 0.0.0.0 --port 8000
```

### Použití jako Python balíček

```python
from shopify_to_feeds.feeds import GoogleFeedGenerator, BingFeedGenerator, ZboziFeedGenerator

# Google Merchant Center
generator = GoogleFeedGenerator("https://example.myshopify.com", download_images=True)
generator.generate("output/google_feed.xml")

# Bing Shopping
generator = BingFeedGenerator("https://example.myshopify.com")
generator.generate("output/bing_feed.xml")

# Zbozi.cz
generator = ZboziFeedGenerator("https://example.myshopify.com")
generator.generate("output/zbozi_feed.xml")
```

## API Endpointy

### Root endpoint
```
GET /
```
Vrátí základní informace o API.

### Spustit aktualizaci feedu
```
POST /feed/update/{store_url}?feed_type=google&download_images=true
```

**Parametry:**
- `store_url`: URL Shopify obchodu (path parameter)
- `feed_type`: Typ feedu (`google`, `bing`, `zbozi`) - query parameter
- `download_images`: Zda stahovat obrázky (pouze pro Google) - query parameter

### Zkontrolovat stav feedu
```
GET /feed/status/{store_url}
```

### Stáhnout feed soubor
```
GET /feeds/{filename}
```

## Příklady použití

### Generování Google Merchant Center feedu
```bash
curl -X POST "http://localhost:8000/feed/update/https://example.myshopify.com?feed_type=google&download_images=true"
```

### Generování Bing Shopping feedu
```bash
curl -X POST "http://localhost:8000/feed/update/https://example.myshopify.com?feed_type=bing"
```

### Generování Zbozi.cz feedu
```bash
curl -X POST "http://localhost:8000/feed/update/https://example.myshopify.com?feed_type=zbozi"
```

### Kontrola stavu
```bash
curl "http://localhost:8000/feed/status/https://example.myshopify.com"
```

### Stažení feedu
```bash
curl "http://localhost:8000/feeds/ed003536_google.xml"
```

## Funkce

- 🔄 Automatické generování XML feedů z Shopify obchodů
- 📦 Podpora pro Google Merchant Center, Bing Shopping a Zbozi.cz
- 🖼️ Volitelné stahování produktových obrázků (Google)
- 🔁 Background processing feedů
- 📊 Status tracking generovaných feedů
- 🚀 REST API pro integraci
- 📁 Statické soubory feedů dostupné přes HTTP
- 🏗️ Modulární architektura pro snadné rozšíření

## Vývoj

### Spuštění v development módu

```bash
# S autoreload
uvicorn shopify_to_feeds.api:app --reload --host 0.0.0.0 --port 8000
```

### Přidání nového feed generátoru

1. Vytvořte novou třídu dědící z `BaseFeedGenerator` v `shopify_to_feeds/feeds/`
2. Implementujte metody `generate()` a `get_feed_type()`
3. Přidejte třídu do `shopify_to_feeds/feeds/__init__.py`
4. Přidejte podporu do API endpointu

## License

MIT License - viz LICENSE soubor
