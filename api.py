from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
import uvicorn
import logging
from datetime import datetime
import os
import hashlib
from GMC_feed import create_xml_feed
from bing_feed import create_xml_feed_from_store as create_bing_feed
from zbozi_feed import create_xml_feed_from_store as create_zbozi_feed

app = FastAPI(title="Listnato Shopify Feeds API")

# Nastavení logování
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Slovník pro sledování stavu feedů
feed_states = {}

# Vytvoření adresáře pro statické soubory
STATIC_DIR = "static/feeds"
os.makedirs(STATIC_DIR, exist_ok=True)

def get_feed_filename(store_url: str, feed_type: str = "google") -> str:
    """Generuje unikátní název souboru pro feed."""
    # Vytvoření hash z URL obchodu
    store_hash = hashlib.md5(store_url.encode()).hexdigest()[:8]
    return f"{store_hash}_{feed_type}.xml"

def get_feed_path(store_url: str, feed_type: str = "google") -> str:
    """Vrací cestu k feed souboru."""
    filename = get_feed_filename(store_url, feed_type)
    return os.path.join(STATIC_DIR, filename)

def get_feed_url(store_url: str, feed_type: str = "google") -> str:
    """Vrací URL feedu."""
    filename = get_feed_filename(store_url, feed_type)
    return f"/feeds/{filename}"

async def update_feed(store_url: str, feed_type: str = "google", download_images: bool = True):
    """Aktualizuje feed v pozadí."""
    try:
        # Validace URL obchodu
        if not store_url.startswith(('http://', 'https://')):
            store_url = f"https://{store_url}"
        
        # Získání cesty k feed souboru
        feed_path = get_feed_path(store_url, feed_type)
        
        # Aktualizace stavu
        feed_states[store_url] = {
            "status": "processing",
            "last_update": datetime.now().isoformat(),
            "feed_url": get_feed_url(store_url, feed_type),
            "download_images": download_images
        }
        
        # Zpracování kolekcí a vytvoření XML feedu
        if feed_type == "google":
            create_xml_feed(store_url, feed_path, download_images)
        elif feed_type == "bing":
            create_bing_feed(store_url, feed_path)
        elif feed_type == "zbozi":
            create_zbozi_feed(store_url, feed_path)
        
        # Aktualizace stavu po úspěšném dokončení
        feed_states[store_url].update({
            "status": "completed",
            "last_update": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error updating feed: {str(e)}")
        feed_states[store_url] = {
            "status": "error",
            "error": str(e),
            "last_update": datetime.now().isoformat()
        }

@app.post("/feed/update/{store_url:path}")
async def trigger_feed_update(store_url: str, background_tasks: BackgroundTasks, feed_type: str = "google", download_images: bool = True):
    """Spustí aktualizaci feedu."""
    if feed_type not in ["google", "bing", "zbozi"]:
        raise HTTPException(status_code=400, detail="Invalid feed type")
    
    background_tasks.add_task(update_feed, store_url, feed_type, download_images)
    return {
        "message": "Feed update started",
        "store_url": store_url,
        "feed_url": get_feed_url(store_url, feed_type),
        "download_images": download_images
    }

@app.get("/feed/status/{store_url:path}")
async def get_feed_status(store_url: str):
    """Vrátí aktuální stav feedu."""
    if store_url not in feed_states:
        raise HTTPException(status_code=404, detail="Feed not found")
    return feed_states[store_url]

@app.get("/feeds/{filename}")
async def get_feed_file(filename: str):
    """Vrátí feed soubor."""
    file_path = os.path.join(STATIC_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Feed file not found")
    return FileResponse(file_path, media_type="application/xml")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000) 