# Listnato Shopify Feeds Generator

FastAPI aplikace pro generování XML feedů z Shopify obchodů pro různé e-commerce platformy.

## Popis

Tento projekt generuje produktové feedy ve formátu XML pro:
- **Google Merchant Center** (GMC)
- **Bing Shopping**
- **Zbozi.cz**

Aplikace poskytuje REST API endpointy pro automatické generování a aktualizaci feedů z Shopify obchodů.

## Funkce

- 🔄 Automatické generování XML feedů z Shopify obchodů
- 📦 Podpora pro Google Merchant Center, Bing Shopping a Zbozi.cz
- 🖼️ Stahování produktových obrázků
- 🔁 Background processing feedů
- 📊 Status tracking generovaných feedů
- 🚀 REST API pro integraci
- 📁 Statické soubory feedů dostupné přes HTTP

## Instalace

```sh
# Nainstalovat závislosti
pip install -r requirements.txt
```

## Spuštění

```sh
# Spustit API server
python api.py

# Nebo pomocí uvicorn
uvicorn api:app --host 0.0.0.0 --port 8000
```

## API Endpointy

### Spustit aktualizaci feedu
```
POST /feed/update/{store_url}?feed_type=google&download_images=true
```

### Zkontrolovat stav feedu
```
GET /feed/status/{store_url}
```

### Stáhnout feed soubor
```
GET /feeds/{filename}
```

## Použití

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

## Konfigurace

Aplikace používá konfigurační soubory pro nginx (`listnato.conf`) a uwsgi (`uwsgi.ini`).