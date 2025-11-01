#!/usr/bin/env python3
"""
Script pro stažení obrázků z Shopify obchodu pro GMC feed.
"""

import sys
import os
import logging
from datetime import datetime
from urllib.parse import urlparse

# Přidání cesty k modulům
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from GMC_feed import create_xml_feed, Settings

def main():
    """Hlavní funkce pro stažení obrázků."""
    if len(sys.argv) < 2:
        print("Použití: python download_images.py <shopify_store_url> [--no-images]")
        print("Příklad: python download_images.py https://example.myshopify.com")
        sys.exit(1)
    
    store_url = sys.argv[1]
    download_images = "--no-images" not in sys.argv
    
    # Nastavení logování
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)
    
    logger.info(f"Spouštím stažení obrázků pro: {store_url}")
    logger.info(f"Stahování obrázků: {'Zapnuto' if download_images else 'Vypnuto'}")
    
    try:
        # Vytvoření feedu s obrázky
        output_path = create_xml_feed(store_url, download_images=download_images)
        
        if download_images:
            # Získání cesty k obrázkům
            parsed_url = urlparse(store_url)
            store_name = parsed_url.netloc.split(".")[0]
            images_folder = os.path.join(Settings.OUTPUT_FOLDER, f"{store_name}_images_*")
            
            logger.info(f"Feed vytvořen: {output_path}")
            logger.info(f"Obrázky uloženy ve složce: {images_folder}")
        else:
            logger.info(f"Feed vytvořen bez obrázků: {output_path}")
            
    except Exception as e:
        logger.error(f"Chyba při vytváření feedu: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main() 