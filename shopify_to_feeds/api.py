#
# Project: shopify-to-feeds
# File:    api.py
#
# Description:
# FastAPI service that triggers feed generation and serves the generated files.
#
# Author:
# Jan Alexandr Kopřiva
# jan.alexandr.kopriva@gmail.com
#
# License: MIT
#

"""
FastAPI application for generating Shopify product feeds.
"""

import hashlib
import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse

from shopify_to_feeds.feeds import BingFeedGenerator, GoogleFeedGenerator, ZboziFeedGenerator
from shopify_to_feeds.security import UrlValidationError, require_feed_api_key, validate_store_url

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

# Feed states tracking. Bounded by count and age so an attacker cannot grow it
# without limit by triggering updates for many distinct store URLs.
feed_states = {}
_feed_states_lock = threading.Lock()

FEED_STATES_MAX = int(os.environ.get("FEED_STATES_MAX", "1000"))
FEED_STATES_TTL = timedelta(seconds=int(os.environ.get("FEED_STATES_TTL", "86400")))

# Cap on concurrent background feed-generation tasks.
MAX_CONCURRENT_TASKS = int(os.environ.get("FEED_MAX_CONCURRENT", "4"))
_task_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT_TASKS)

# Static directory for feeds
STATIC_DIR = "static/feeds"
Path(STATIC_DIR).mkdir(parents=True, exist_ok=True)


def _evict_feed_states(now: datetime | None = None) -> None:
    """
    Evict expired and excess feed-state entries. Caller must hold the lock.

    Bounded by age (FEED_STATES_TTL) and count (FEED_STATES_MAX), oldest first.
    """
    now = now or datetime.now()

    expired = []
    for key, state in feed_states.items():
        ts = state.get("last_update")
        if not ts:
            continue
        try:
            updated = datetime.fromisoformat(ts)
        except (TypeError, ValueError):
            continue
        if now - updated > FEED_STATES_TTL:
            expired.append(key)
    for key in expired:
        feed_states.pop(key, None)

    if len(feed_states) > FEED_STATES_MAX:
        ordered = sorted(feed_states.items(), key=lambda item: item[1].get("last_update") or "")
        for key, _ in ordered[: len(feed_states) - FEED_STATES_MAX]:
            feed_states.pop(key, None)


def _set_feed_state(store_url: str, state: dict) -> None:
    """Thread-safe write of a feed state, with bounded eviction."""
    with _feed_states_lock:
        feed_states[store_url] = state
        _evict_feed_states()


def _update_feed_state(store_url: str, updates: dict) -> None:
    """Thread-safe in-place update of an existing feed state."""
    with _feed_states_lock:
        if store_url in feed_states:
            feed_states[store_url].update(updates)


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
    return str(Path(STATIC_DIR) / filename)


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


def resolve_feed_file(filename: str) -> Path:
    """
    Resolve a requested feed filename to a path inside STATIC_DIR.

    The filename arrives from the URL, so it is untrusted: reject anything
    carrying a path separator or traversal segment, and verify the resolved
    path still sits inside the feed directory.

    Args:
        filename: Requested feed file name

    Returns:
        Resolved path inside STATIC_DIR

    Raises:
        HTTPException: 404 if the name escapes STATIC_DIR or does not exist
    """
    if not filename or "/" in filename or "\\" in filename or filename in (".", ".."):
        raise HTTPException(status_code=404, detail="Feed file not found")

    root = Path(STATIC_DIR).resolve()
    candidate = (root / filename).resolve()
    if candidate != root and root not in candidate.parents:
        logger.warning("Rejected feed file outside static dir: %s", filename)
        raise HTTPException(status_code=404, detail="Feed file not found")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Feed file not found")
    return candidate


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
    # SSRF guard: validate and normalize before any server-side fetch.
    try:
        store_url = validate_store_url(store_url)
    except UrlValidationError as e:
        logger.warning("Rejected feed update for invalid store URL: %s", e)
        _set_feed_state(store_url, {
            "status": "error",
            "last_update": datetime.now().isoformat()
        })
        return

    # Refuse the task if too many feed generations are already running.
    if not _task_semaphore.acquire(blocking=False):
        logger.warning("Feed task rejected: concurrency cap reached")
        _set_feed_state(store_url, {
            "status": "error",
            "last_update": datetime.now().isoformat()
        })
        return

    try:
        feed_path = get_feed_path(store_url, feed_type)

        # Update state
        _set_feed_state(store_url, {
            "status": "processing",
            "last_update": datetime.now().isoformat(),
            "feed_url": get_feed_url(store_url, feed_type),
            "download_images": download_images
        })

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
        _update_feed_state(store_url, {
            "status": "completed",
            "last_update": datetime.now().isoformat()
        })

        logger.info(f"Feed generation completed for {store_url} ({feed_type})")

    except Exception:
        # The error text can carry internal detail, so it is logged but not stored.
        logger.exception("Error updating feed")
        _set_feed_state(store_url, {
            "status": "error",
            "last_update": datetime.now().isoformat()
        })
    finally:
        _task_semaphore.release()


@app.post("/feed/update/{store_url:path}", dependencies=[Depends(require_feed_api_key)])
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

    # Reject a bad store URL up front so the caller sees it, rather than only
    # discovering it later through the feed status.
    try:
        store_url = validate_store_url(store_url)
    except UrlValidationError as e:
        raise HTTPException(status_code=400, detail=f"Invalid store URL: {e}") from e

    background_tasks.add_task(update_feed, store_url, feed_type, download_images)
    return {
        "message": "Feed update started",
        "store_url": store_url,
        "feed_type": feed_type,
        "feed_url": get_feed_url(store_url, feed_type),
        "download_images": download_images
    }


@app.get("/feed/status/{store_url:path}", dependencies=[Depends(require_feed_api_key)])
async def get_feed_status(store_url: str):
    """
    Get feed generation status.

    Args:
        store_url: Shopify store URL

    Returns:
        Feed status information
    """
    with _feed_states_lock:
        state = feed_states.get(store_url)
        if state is None:
            raise HTTPException(status_code=404, detail="Feed not found")
        return dict(state)


@app.get("/feeds/{filename}")
async def get_feed_file(filename: str):
    """
    Get feed file.

    Args:
        filename: Name of feed file

    Returns:
        Feed XML file
    """
    return FileResponse(resolve_feed_file(filename), media_type="application/xml")


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
    uvicorn.run(
        app,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000"))
    )
