"""
FastAPI application for generating Shopify product feeds.
"""

import os
import hashlib
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from shopify_to_feeds.feeds import GoogleFeedGenerator, BingFeedGenerator, ZboziFeedGenerator


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Shopify to Feeds API",
    description="Universal tool for generating product feeds from Shopify stores",
    version="1.0.0"
)

# Feed states tracking
feed_states = {}

# Static directory for feeds
STATIC_DIR = "static/feeds"
os.makedirs(STATIC_DIR, exist_ok=True)


def get_feed_filename(store_url: str, feed_type: str = "google") -> str:
    """
    Generate unique filename for feed.

    Args:
        store_url: Shopify store URL
        feed_type: Type of feed (google, bing, zbozi)

    Returns:
        Unique filename
    """
    store_hash = hashlib.md5(store_url.encode()).hexdigest()[:8]
    return f"{store_hash}_{feed_type}.xml"


def get_feed_path(store_url: str, feed_type: str = "google") -> str:
    """
    Get path to feed file.

    Args:
        store_url: Shopify store URL
        feed_type: Type of feed

    Returns:
        Full path to feed file
    """
    filename = get_feed_filename(store_url, feed_type)
    return os.path.join(STATIC_DIR, filename)


def get_feed_url(store_url: str, feed_type: str = "google") -> str:
    """
    Get URL path to feed file.

    Args:
        store_url: Shopify store URL
        feed_type: Type of feed

    Returns:
        URL path to feed
    """
    filename = get_feed_filename(store_url, feed_type)
    return f"/feeds/{filename}"


async def update_feed(
    store_url: str,
    feed_type: str = "google",
    download_images: bool = True
):
    """
    Update feed in background.

    Args:
        store_url: Shopify store URL
        feed_type: Type of feed to generate
        download_images: Whether to download product images
    """
    try:
        # Validate URL
        if not store_url.startswith(('http://', 'https://')):
            store_url = f"https://{store_url}"

        feed_path = get_feed_path(store_url, feed_type)

        # Update state
        feed_states[store_url] = {
            "status": "processing",
            "last_update": datetime.now().isoformat(),
            "feed_url": get_feed_url(store_url, feed_type),
            "download_images": download_images
        }

        # Generate feed based on type
        if feed_type == "google":
            generator = GoogleFeedGenerator(
                store_url,
                download_images=download_images
            )
        elif feed_type == "bing":
            generator = BingFeedGenerator(store_url)
        elif feed_type == "zbozi":
            generator = ZboziFeedGenerator(store_url)
        else:
            raise ValueError(f"Unknown feed type: {feed_type}")

        generator.generate(feed_path)

        # Update state after completion
        feed_states[store_url].update({
            "status": "completed",
            "last_update": datetime.now().isoformat()
        })

        logger.info(f"Feed generation completed for {store_url} ({feed_type})")

    except Exception as e:
        logger.error(f"Error updating feed: {str(e)}")
        feed_states[store_url] = {
            "status": "error",
            "error": str(e),
            "last_update": datetime.now().isoformat()
        }


@app.post("/feed/update/{store_url:path}")
async def trigger_feed_update(
    store_url: str,
    background_tasks: BackgroundTasks,
    feed_type: str = "google",
    download_images: bool = True
):
    """
    Trigger feed update for a Shopify store.

    Args:
        store_url: Shopify store URL
        background_tasks: FastAPI background tasks
        feed_type: Type of feed (google, bing, zbozi)
        download_images: Whether to download product images (Google only)

    Returns:
        Response with feed update status
    """
    if feed_type not in ["google", "bing", "zbozi"]:
        raise HTTPException(status_code=400, detail="Invalid feed type. Must be: google, bing, or zbozi")

    background_tasks.add_task(update_feed, store_url, feed_type, download_images)
    return {
        "message": "Feed update started",
        "store_url": store_url,
        "feed_type": feed_type,
        "feed_url": get_feed_url(store_url, feed_type),
        "download_images": download_images
    }


@app.get("/feed/status/{store_url:path}")
async def get_feed_status(store_url: str):
    """
    Get feed generation status.

    Args:
        store_url: Shopify store URL

    Returns:
        Feed status information
    """
    if store_url not in feed_states:
        raise HTTPException(status_code=404, detail="Feed not found")
    return feed_states[store_url]


@app.get("/feeds/{filename}")
async def get_feed_file(filename: str):
    """
    Get feed file.

    Args:
        filename: Name of feed file

    Returns:
        Feed XML file
    """
    file_path = os.path.join(STATIC_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Feed file not found")
    return FileResponse(file_path, media_type="application/xml")


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Shopify to Feeds API",
        "version": "1.0.0",
        "description": "Universal tool for generating product feeds from Shopify stores",
        "endpoints": {
            "update_feed": "POST /feed/update/{store_url}?feed_type=google&download_images=true",
            "feed_status": "GET /feed/status/{store_url}",
            "get_feed": "GET /feeds/{filename}"
        },
        "supported_feeds": ["google", "bing", "zbozi"]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

