import time
import re
import os
import logging
import requests
from datetime import datetime
from urllib.parse import urlparse, urljoin
import argparse
import xml.etree.ElementTree as ET
from xml.dom import minidom
import sys
import concurrent.futures
from typing import List, Dict, Any
from queue import Queue
from threading import Lock
from utils.shopify_scraper import download_image

# Nastavení logování
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Settings:
    """
    A class to store the application settings.
    Modify this class to change the default settings for the scraper.
    """

    # Output folder for the extracted data
    OUTPUT_FOLDER = "google_feed_exports"

    # XML file name for the exported product data
    XML_FILENAME = "google_products.xml"

    # Maximum number of retries for failed requests
    MAX_RETRIES = 3

    # Delay between retries (in seconds)
    RETRY_DELAY = 180

    # User agent string for the HTTP requests
    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36"

    # Default currency
    DEFAULT_CURRENCY = "CZK"

    # Default shipping settings (can be overridden in Merchant Center)
    DEFAULT_SHIPPING = {
        "country": "CZ",
        "service": "Standard",
        "price": "0 CZK",
        "carrier_shipping": "yes",
        "shipping_transit_business_days": "3-5"
    }

    # Default tax settings (can be overridden in Merchant Center)
    DEFAULT_TAX = {
        "country": "CZ",
        "rate": "21.0",
        "tax_ship": "yes"
    }

    # Weight unit conversion (grams to kg)
    WEIGHT_UNIT = "kg"

    # Number of worker threads for parallel processing
    MAX_WORKERS = 4

    # Number of products to process in each batch
    BATCH_SIZE = 10


def setup_logging():
    """Setup logging configuration with detailed console output."""
    # Create a custom formatter
    class ColoredFormatter(logging.Formatter):
        """Custom formatter with colors and detailed information."""
        
        grey = "\x1b[38;21m"
        blue = "\x1b[38;5;39m"
        yellow = "\x1b[38;5;226m"
        red = "\x1b[38;5;196m"
        bold_red = "\x1b[31;1m"
        reset = "\x1b[0m"

        def __init__(self, fmt):
            super().__init__()
            self.fmt = fmt
            self.FORMATS = {
                logging.DEBUG: self.grey + self.fmt + self.reset,
                logging.INFO: self.blue + self.fmt + self.reset,
                logging.WARNING: self.yellow + self.fmt + self.reset,
                logging.ERROR: self.red + self.fmt + self.reset,
                logging.CRITICAL: self.bold_red + self.fmt + self.reset
            }

        def format(self, record):
            log_fmt = self.FORMATS.get(record.levelno)
            formatter = logging.Formatter(log_fmt)
            return formatter.format(record)

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    
    # Create formatter
    formatter = ColoredFormatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(formatter)

    # Setup root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(console_handler)

    return logger


def validate_url(url):
    """Validate and correct URL format."""
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url.rstrip('/')


def remove_html_tags(text):
    """Remove HTML tags and limit description to 5000 characters"""
    cleaned = re.sub("<[^<]+?>", "", text)
    return cleaned[:5000]  # Google's recommended limit


def format_price(price, currency=None):
    """Format price with currency."""
    if currency is None:
        currency = Settings.DEFAULT_CURRENCY
    return f"{float(price):.2f} {currency}"


def format_weight(grams):
    """Convert grams to kg and format weight."""
    if not grams:
        return None
    return f"{float(grams) / 1000:.3f} {Settings.WEIGHT_UNIT}"


def make_request(url, headers=None):
    """Make a GET request with retry logic."""
    if headers is None:
        headers = {"User-Agent": Settings.USER_AGENT}

    for attempt in range(Settings.MAX_RETRIES):
        try:
            logging.info(f"Making request to {url} (Attempt {attempt + 1}/{Settings.MAX_RETRIES})")
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            logging.info(f"Request successful: {response.status_code}")
            return response.json()
        except requests.RequestException as e:
            logging.warning(
                f"Request failed (attempt {attempt + 1}/{Settings.MAX_RETRIES}): {str(e)}"
            )
            if attempt < Settings.MAX_RETRIES - 1:
                logging.info(f"Retrying in {Settings.RETRY_DELAY} seconds...")
                time.sleep(Settings.RETRY_DELAY)

    logging.error(f"Failed to retrieve data from {url} after {Settings.MAX_RETRIES} attempts")
    return None


def get_page(url, page, collection_handle=None):
    """Fetch a page of products from a Shopify store."""
    full_url = urljoin(url, f"/products.json?page={page}")
    if collection_handle:
        full_url = urljoin(url, f"/collections/{collection_handle}/products.json?page={page}")
        logging.info(f"Fetching products from collection: {collection_handle} (page {page})")
    else:
        logging.info(f"Fetching all products (page {page})")

    data = make_request(full_url)
    products = data["products"] if data else []
    logging.info(f"Found {len(products)} products on page {page}")
    return products


def get_page_collections(url):
    """Generator to fetch all collections from a Shopify store."""
    page = 1
    total_collections = 0
    
    while True:
        full_url = urljoin(url, f"/collections.json?page={page}")
        logging.info(f"Fetching collections (page {page})")
        
        data = make_request(full_url)
        if not data or not data["collections"]:
            break
            
        collections = data["collections"]
        total_collections += len(collections)
        logging.info(f"Found {len(collections)} collections on page {page}")
        
        for collection in collections:
            logging.info(f"Processing collection: {collection['title']} ({collection['handle']})")
            yield collection
            
        page += 1
    
    logging.info(f"Total collections found: {total_collections}")


def get_variant_images(product, variant_id):
    """Get all images associated with a specific variant."""
    variant_images = []
    for image in product.get("images", []):
        if variant_id in image.get("variant_ids", []):
            variant_images.append(image["src"])
    return variant_images


def process_product(product, base_url):
    """Process a single product and its variants."""
    variants = []
    
    # Get product images - handle case where images might be missing
    image_links = []
    if "images" in product:
        image_links = [img["src"] for img in product["images"]]
    elif "image" in product:
        image_links = [product["image"]["src"]]
    
    # Get product type and tags
    product_type = product.get("product_type", "")
    product_tags = product.get("tags", "")
    
    # Process each variant
    for variant in product.get("variants", []):
        try:
            # Get variant details
            variant_id = variant.get("id", "")
            variant_title = variant.get("title", "Default Title")
            variant_sku = variant.get("sku", "")
            variant_price = variant.get("price", "0.0")
            variant_available = variant.get("available", False)
            
            # Create variant data
            variant_data = {
                "g:id": str(variant_id),
                "title": f"{product.get('title', '')} - {variant_title}",
                "description": remove_html_tags(product.get("body_html", "")),
                "link": f"{base_url}/products/{product.get('handle', '')}",
                "g:image_link": image_links[0] if image_links else "",
                "g:price": f"{variant_price} {Settings.DEFAULT_CURRENCY}",
                "g:availability": "in stock" if variant_available else "out of stock",
                "g:condition": "new",
                "g:brand": product.get("vendor", ""),
                "g:gtin": variant_sku,
                "g:mpn": variant_sku,
                "g:shipping": {
                    "g:country": "CZ",
                    "g:service": "Standard",
                    "g:price": "0 CZK",
                    "g:carrier_shipping": "true",
                    "g:shipping_transit_business_days": "2"
                },
                "g:tax": {
                    "g:country": "CZ",
                    "g:rate": "21.0",
                    "g:tax_ship": "y"
                }
            }
            
            # Add optional fields if available
            if product_type:
                variant_data["g:product_type"] = product_type
            if product_tags:
                variant_data["g:google_product_category"] = product_tags
            
            # Add additional images if available
            if len(image_links) > 1:
                variant_data["g:additional_image_link"] = image_links[1:]
            
            variants.append(variant_data)
            
        except Exception as e:
            logging.error(f"Error processing variant {variant.get('id', 'unknown')}: {str(e)}")
            continue
    
    return variants


def process_collection(store_url: str, collection_handle: str) -> List[Dict]:
    """Zpracuje kolekci a vrátí seznam variant produktů."""
    variants = []
    page = 1
    
    while True:
        logger.info(f"Fetching products from collection: {collection_handle} (page {page})")
        url = f"{store_url}/collections/{collection_handle}/products.json?page={page}"
        response = make_request(url)
        
        if not response or "products" not in response:
            break
            
        products = response["products"]
        if not products:
            break
            
        logger.info(f"Found {len(products)} products on page {page}")
        
        for product in products:
            # Získání základních informací o produktu
            product_id = str(product.get("id", ""))
            product_title = product.get("title", "")
            product_description = remove_html_tags(product.get("body_html", ""))
            product_link = f"{store_url}/products/{product.get('handle', '')}"
            
            # Zpracování variant
            for variant in product.get("variants", []):
                variant_id = str(variant.get("id", ""))
                if not variant_id:
                    continue
                    
                # Získání obrázku pro variantu
                image_url = ""
                for image in product.get("images", []):
                    if image.get("id") == variant.get("image_id"):
                        image_url = image.get("src", "")
                        break
                if not image_url and product.get("images"):
                    image_url = product.get("images")[0].get("src", "")
                
                # Sestavení dat varianty
                variant_data = {
                    "id": variant_id,
                    "title": f"{product_title} - {variant.get('title', '')}",
                    "description": product_description,
                    "link": product_link,
                    "image_link": image_url,
                    "availability": "in stock" if variant.get("available", False) else "out of stock",
                    "price": f"{variant.get('price', '0.00')} CZK",
                    "brand": "Coasy",
                    "condition": "new",
                    "google_product_category": "Home & Garden > Plants",
                }
                
                # Přidání volitelných atributů
                if variant.get("sku"):
                    variant_data["gtin"] = variant["sku"]
                if variant.get("barcode"):
                    variant_data["mpn"] = variant["barcode"]
                
                variants.append(variant_data)
        
        page += 1
    
    logger.info(f"Collection {collection_handle} processed: {len(variants)} variants")
    return variants


def setup_output_folders(output_folder):
    """Create the necessary output folders if they don't exist."""
    if not os.path.exists(output_folder):
        logging.info(f"Creating output folder: {output_folder}")
        os.makedirs(output_folder)
    return output_folder


def get_shop_info(shop_url):
    """Get shop information from Shopify store."""
    try:
        # Zkusíme získat informace z prvního produktu
        url = f"{shop_url}/products.json?limit=1"
        data = make_request(url)
        if data and "products" in data and data["products"]:
            product = data["products"][0]
            return {
                "name": product.get("vendor", ""),  # Použijeme vendor jako název obchodu
                "description": "",  # Prázdný popis
                "url": shop_url
            }
        return None
    except Exception as e:
        logging.error(f"Error fetching shop info: {str(e)}")
        return None


def create_xml_feed(store_url: str, output_path: str = None, download_images: bool = True) -> str:
    """Vytvoří XML feed pro Google Merchant Center."""
    try:
        # Validace URL obchodu
        if not store_url.startswith(('http://', 'https://')):
            store_url = f"https://{store_url}"
        
        # Získání všech kolekcí
        collections = list(get_page_collections(store_url))
        all_variants = []
        
        # Zpracování kolekcí
        for collection in collections:
            try:
                variants = process_collection(store_url, collection["handle"])
                all_variants.extend(variants)
            except Exception as e:
                logger.error(f"Error processing collection {collection['handle']}: {str(e)}")
        
        # Stáhnutí obrázků, pokud je požadováno
        if download_images and all_variants:
            # Vytvoření složky pro obrázky
            parsed_url = urlparse(store_url)
            store_name = parsed_url.netloc.split(".")[0]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            images_folder = os.path.join(Settings.OUTPUT_FOLDER, f"{store_name}_images_{timestamp}")
            
            logger.info(f"Starting image download to folder: {images_folder}")
            downloaded_images = download_product_images(all_variants, images_folder)
            logger.info(f"Image download completed. Downloaded {len(downloaded_images)} images")
        
        # Získání informací o obchodu
        shop_info = get_shop_info(store_url)
        
        # Registrace namespace pro správný prefix g:
        ET.register_namespace('g', 'http://base.google.com/ns/1.0')
        
        # Vytvoření XML feedu
        root = ET.Element("rss", {
            "version": "2.0",
            "xmlns:g": "http://base.google.com/ns/1.0"
        })
        
        channel = ET.SubElement(root, "channel")
        
        # Přidání informací o obchodu
        ET.SubElement(channel, "title").text = shop_info["name"]
        ET.SubElement(channel, "link").text = shop_info["url"]
        ET.SubElement(channel, "description").text = shop_info["description"]
        
        # Přidání produktů
        for variant in all_variants:
            item = ET.SubElement(channel, "item")
            
            # Povinné atributy
            g_id = ET.SubElement(item, "{http://base.google.com/ns/1.0}id")
            g_id.text = str(variant["id"])
            
            g_title = ET.SubElement(item, "{http://base.google.com/ns/1.0}title")
            g_title.text = variant["title"].replace(" - Default Title", "")
            
            g_description = ET.SubElement(item, "{http://base.google.com/ns/1.0}description")
            g_description.text = variant["description"]
            
            g_link = ET.SubElement(item, "{http://base.google.com/ns/1.0}link")
            g_link.text = variant["link"]
            
            g_image_link = ET.SubElement(item, "{http://base.google.com/ns/1.0}image_link")
            g_image_link.text = variant["image_link"]
            
            g_availability = ET.SubElement(item, "{http://base.google.com/ns/1.0}availability")
            g_availability.text = variant["availability"]
            
            g_price = ET.SubElement(item, "{http://base.google.com/ns/1.0}price")
            g_price.text = variant["price"]
            
            g_brand = ET.SubElement(item, "{http://base.google.com/ns/1.0}brand")
            g_brand.text = variant["brand"]
            
            g_condition = ET.SubElement(item, "{http://base.google.com/ns/1.0}condition")
            g_condition.text = variant["condition"]
            
            g_google_product_category = ET.SubElement(item, "{http://base.google.com/ns/1.0}google_product_category")
            g_google_product_category.text = variant["google_product_category"]
            
            # Přidání identifier_exists tagu
            g_identifier_exists = ET.SubElement(item, "{http://base.google.com/ns/1.0}identifier_exists")
            g_identifier_exists.text = "FALSE"  # Nastavíme na FALSE, pokud nemáme GTIN nebo MPN
            
            # Volitelné atributy
            if "gtin" in variant:
                g_gtin = ET.SubElement(item, "{http://base.google.com/ns/1.0}gtin")
                g_gtin.text = variant["gtin"]
                g_identifier_exists.text = "TRUE"  # Pokud máme GTIN, nastavíme na TRUE
            if "mpn" in variant:
                g_mpn = ET.SubElement(item, "{http://base.google.com/ns/1.0}mpn")
                g_mpn.text = variant["mpn"]
                g_identifier_exists.text = "TRUE"  # Pokud máme MPN, nastavíme na TRUE
            if "color" in variant:
                g_color = ET.SubElement(item, "{http://base.google.com/ns/1.0}color")
                g_color.text = variant["color"]
            if "size" in variant:
                g_size = ET.SubElement(item, "{http://base.google.com/ns/1.0}size")
                g_size.text = variant["size"]
            if "material" in variant:
                g_material = ET.SubElement(item, "{http://base.google.com/ns/1.0}material")
                g_material.text = variant["material"]
            if "pattern" in variant:
                g_pattern = ET.SubElement(item, "{http://base.google.com/ns/1.0}pattern")
                g_pattern.text = variant["pattern"]
            if "gender" in variant:
                g_gender = ET.SubElement(item, "{http://base.google.com/ns/1.0}gender")
                g_gender.text = variant["gender"]
            if "age_group" in variant:
                g_age_group = ET.SubElement(item, "{http://base.google.com/ns/1.0}age_group")
                g_age_group.text = variant["age_group"]
            if "shipping" in variant:
                g_shipping = ET.SubElement(item, "{http://base.google.com/ns/1.0}shipping")
                g_country = ET.SubElement(g_shipping, "{http://base.google.com/ns/1.0}country")
                g_country.text = variant["shipping"]["country"]
                g_service = ET.SubElement(g_shipping, "{http://base.google.com/ns/1.0}service")
                g_service.text = variant["shipping"]["service"]
                g_price = ET.SubElement(g_shipping, "{http://base.google.com/ns/1.0}price")
                g_price.text = variant["shipping"]["price"]
        
        # Vytvoření XML souboru
        tree = ET.ElementTree(root)
        if output_path is None:
            output_path = os.path.join(Settings.OUTPUT_FOLDER, Settings.XML_FILENAME)
        
        # Vytvoření adresáře, pokud neexistuje
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Uložení souboru
        tree.write(output_path, encoding="utf-8", xml_declaration=True)
        logger.info(f"Feed saved to {output_path}")
        
        logger.info(f"Feed update completed for {store_url}: {len(all_variants)} products")
        return output_path
        
    except Exception as e:
        logger.error(f"Error creating feed: {str(e)}")
        raise


def download_product_images(products_data, images_folder):
    """
    Download images for all products in the feed.
    
    Args:
        products_data (List[Dict]): List of product data dictionaries
        images_folder (str): Path to the folder where images should be saved
    
    Returns:
        Dict: Dictionary mapping product IDs to downloaded image filenames
    """
    if not os.path.exists(images_folder):
        os.makedirs(images_folder)
        logger.info(f"Created images folder: {images_folder}")
    
    downloaded_images = {}
    total_images = 0
    
    # Collect all unique image URLs
    image_urls = set()
    for product in products_data:
        if "image_link" in product and product["image_link"]:
            image_urls.add(product["image_link"])
        if "additional_image_link" in product:
            for img_url in product["additional_image_link"]:
                image_urls.add(img_url)
    
    total_images = len(image_urls)
    logger.info(f"Found {total_images} unique images to download")
    
    if total_images == 0:
        logger.info("No images found to download")
        return downloaded_images
    
    # Download images using ThreadPoolExecutor for parallel processing
    with concurrent.futures.ThreadPoolExecutor(max_workers=Settings.MAX_WORKERS) as executor:
        future_to_url = {
            executor.submit(download_image, url, images_folder): url 
            for url in image_urls
        }
        
        for i, future in enumerate(concurrent.futures.as_completed(future_to_url), 1):
            url = future_to_url[future]
            try:
                filename = future.result()
                if filename:
                    downloaded_images[url] = filename
                    logger.debug(f"Downloaded image: {filename}")
                
                if i % 10 == 0 or i == total_images:
                    logger.info(f"Downloaded {i}/{total_images} images")
                    
            except Exception as e:
                logger.error(f"Error downloading image from {url}: {str(e)}")
    
    logger.info(f"Image download completed. Downloaded {len(downloaded_images)} images")
    return downloaded_images


def main():
    parser = argparse.ArgumentParser(description="Generate Google Shopping XML feed from Shopify store")
    parser.add_argument("url", help="URL of the Shopify store")
    parser.add_argument("--collections", nargs="+", help="Specific collections to scrape (optional)")
    parser.add_argument("--workers", type=int, default=Settings.MAX_WORKERS,
                      help=f"Number of worker threads (default: {Settings.MAX_WORKERS})")
    args = parser.parse_args()

    # Update number of workers if specified
    Settings.MAX_WORKERS = args.workers

    # Setup logging
    logger = setup_logging()
    logger.info("Starting Google Shopping feed generation")

    # Validate URL
    base_url = validate_url(args.url)
    logger.info(f"Using base URL: {base_url}")

    # Setup output folder
    output_folder = setup_output_folders(Settings.OUTPUT_FOLDER)
    output_path = os.path.join(output_folder, Settings.XML_FILENAME)

    # Extract products
    products = []
    if args.collections:
        logger.info(f"Processing specific collections: {', '.join(args.collections)}")
        # Process collections in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=Settings.MAX_WORKERS) as executor:
            futures = [executor.submit(process_collection, base_url, collection) for collection in args.collections]
            for future in concurrent.futures.as_completed(futures):
                try:
                    variants = future.result()
                    products.extend(variants)
                except Exception as e:
                    logger.error(f"Error processing collection: {str(e)}")
    else:
        logger.info("Processing all collections")
        collections = list(get_page_collections(base_url))
        # Process collections in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=Settings.MAX_WORKERS) as executor:
            futures = [executor.submit(process_collection, base_url, collection["handle"]) for collection in collections]
            for future in concurrent.futures.as_completed(futures):
                try:
                    variants = future.result()
                    products.extend(variants)
                except Exception as e:
                    logger.error(f"Error processing collection: {str(e)}")

    logger.info(f"Total products collected: {len(products)}")

    # Create XML feed
    create_xml_feed(base_url, output_path)
    logger.info("Feed generation completed successfully")


if __name__ == "__main__":
    main() 