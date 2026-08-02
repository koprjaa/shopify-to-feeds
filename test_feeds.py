#!/usr/bin/env python3
"""
Test script for generating all feeds for listnato.cz
"""

import logging
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from shopify_to_feeds.feeds import BingFeedGenerator, GoogleFeedGenerator, ZboziFeedGenerator

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Store URL - zkusíme různé varianty
STORE_URLS = [
    "https://listnato.cz",
    "https://listnato.myshopify.com",
]

# Output directory
OUTPUT_DIR = Path("test_feeds")
OUTPUT_DIR.mkdir(exist_ok=True)


def test_store_url(url: str) -> bool:
    """Test if store URL is accessible."""
    import requests
    try:
        test_url = f"{url}/products.json?limit=1"
        response = requests.get(test_url, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.debug(f"URL {url} not accessible: {e}")
        return False


def find_valid_store_url() -> str:
    """Find valid Shopify store URL."""
    for url in STORE_URLS:
        logger.info(f"Testing store URL: {url}")
        if test_store_url(url):
            logger.info(f"✓ Found valid store URL: {url}")
            return url

    # Pokud žádná nefunguje, použijeme první jako fallback
    logger.warning(f"No valid URL found, using first: {STORE_URLS[0]}")
    return STORE_URLS[0]


def test_google_feed(store_url: str) -> bool:
    """Test Google Merchant Center feed generation."""
    try:
        logger.info("=" * 60)
        logger.info("Testing Google Merchant Center feed...")
        logger.info("=" * 60)

        generator = GoogleFeedGenerator(store_url, download_images=False)
        output_path = OUTPUT_DIR / "google_feed.xml"
        result = generator.generate(str(output_path))

        if Path(result).exists():
            file_size = Path(result).stat().st_size
            logger.info(f"✓ Google feed generated successfully: {result} ({file_size:,} bytes)")
            return True
        logger.error(f"✗ Google feed file not found: {result}")
        return False
    except Exception:
        logger.exception("✗ Error generating Google feed")
        return False


def test_bing_feed(store_url: str) -> bool:
    """Test Bing Shopping feed generation."""
    try:
        logger.info("=" * 60)
        logger.info("Testing Bing Shopping feed...")
        logger.info("=" * 60)

        generator = BingFeedGenerator(store_url)
        output_path = OUTPUT_DIR / "bing_feed.xml"
        result = generator.generate(str(output_path))

        if Path(result).exists():
            file_size = Path(result).stat().st_size
            logger.info(f"✓ Bing feed generated successfully: {result} ({file_size:,} bytes)")
            return True
        logger.error(f"✗ Bing feed file not found: {result}")
        return False
    except Exception:
        logger.exception("✗ Error generating Bing feed")
        return False


def test_zbozi_feed(store_url: str) -> bool:
    """Test Zbozi.cz feed generation."""
    try:
        logger.info("=" * 60)
        logger.info("Testing Zbozi.cz feed...")
        logger.info("=" * 60)

        generator = ZboziFeedGenerator(store_url)
        output_path = OUTPUT_DIR / "zbozi_feed.xml"
        result = generator.generate(str(output_path))

        if Path(result).exists():
            file_size = Path(result).stat().st_size
            logger.info(f"✓ Zbozi feed generated successfully: {result} ({file_size:,} bytes)")
            return True
        logger.error(f"✗ Zbozi feed file not found: {result}")
        return False
    except Exception:
        logger.exception("✗ Error generating Zbozi feed")
        return False


def main():
    """Main test function."""
    logger.info("Starting feed generation tests for listnato.cz")
    logger.info("=" * 60)

    # Find valid store URL
    store_url = find_valid_store_url()
    logger.info(f"Using store URL: {store_url}")
    logger.info("")

    # Test all feeds
    results = {
        "Google": test_google_feed(store_url),
        "Bing": test_bing_feed(store_url),
        "Zbozi": test_zbozi_feed(store_url),
    }

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("TEST SUMMARY")
    logger.info("=" * 60)

    for feed_type, success in results.items():
        status = "✓ PASSED" if success else "✗ FAILED"
        logger.info(f"{feed_type:15} {status}")

    total = len(results)
    passed = sum(results.values())

    logger.info("")
    logger.info(f"Total: {passed}/{total} feeds generated successfully")

    if passed == total:
        logger.info("🎉 All feeds generated successfully!")
        return 0
    logger.error(f"❌ {total - passed} feed(s) failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())

