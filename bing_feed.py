import time
import re
import os
import logging
import requests
import argparse
import xml.etree.ElementTree as ET
import concurrent.futures
from urllib.parse import urljoin
from datetime import datetime

class Settings:
    """Nastavení aplikace."""
    OUTPUT_FOLDER = "bing_feed_exports"
    XML_FILENAME = "bing_products.xml"
    MAX_RETRIES = 3
    RETRY_DELAY = 5
    LOG_LEVEL = logging.INFO
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    DEFAULT_CURRENCY = "CZK"
    DEFAULT_SHIPPING = {
        "PPL": {
            "price": 0,
            "country": "CZ"
        }
    }
    MAX_WORKERS = 4
    BATCH_SIZE = 10

def remove_html_tags(text):
    """Remove HTML tags and clean up the text."""
    if not text:
        return ""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Remove multiple spaces
    text = re.sub(r'\s+', ' ', text)
    # Remove HTML entities
    text = re.sub(r'&[^;]+;', '', text)
    # Add spaces after punctuation
    text = re.sub(r'([.,!?])([^\s])', r'\1 \2', text)
    # Add spaces between paragraphs
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    # Clean up special characters
    text = re.sub(r'[^\w\s.,!?-]', '', text)
    # Strip whitespace
    text = text.strip()
    return text

def validate_url(url):
    """Validate URL format."""
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url

def make_request(url, retries=Settings.MAX_RETRIES):
    """Make HTTP request with retry logic."""
    headers = {'User-Agent': Settings.USER_AGENT}
    
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if attempt == retries - 1:
                raise
            time.sleep(Settings.RETRY_DELAY)
    return None

def get_products_pages(shop_url):
    """Get all pages of products from the shop."""
    products = []
    page = 1
    
    while True:
        try:
            url = f"{shop_url}/products.json?limit=250&page={page}"
            data = make_request(url)
            
            if not data or not data.get("products"):
                break
                
            products.extend(data["products"])
            page += 1
            
        except Exception as e:
            logging.error(f"Error fetching page {page}: {str(e)}")
            break
    
    return products

def get_collections(shop_url):
    """Get all collections from the shop."""
    try:
        url = f"{shop_url}/collections.json?limit=250"
        data = make_request(url)
        return data.get("collections", [])
    except Exception as e:
        logging.error(f"Error fetching collections: {str(e)}")
        return []

def get_collection_products(shop_url, collection_id):
    """Get all products from a collection."""
    products = []
    page = 1
    
    while True:
        try:
            url = f"{shop_url}/collections/{collection_id}/products.json?limit=250&page={page}"
            data = make_request(url)
            
            if not data or not data.get("products"):
                break
                
            products.extend(data["products"])
            page += 1
            
        except Exception as e:
            logging.error(f"Error fetching collection products: {str(e)}")
            break
    
    return products

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

def process_product(product, base_url):
    """Process a single product and its variants."""
    variants = []
    for variant in product["variants"]:
        # Základní data produktu
        variant_data = {
            "ProductID": str(variant["id"]),
            "Title": f"{product['title']} - {variant['title']}" if variant['title'] != "Default Title" else product['title'],
            "Link": urljoin(base_url, f"/products/{product['handle']}?variant={variant['id']}"),
            "ImageLink": product["images"][0]["src"] if product.get("images") else "",
            "Price": f"{int(float(variant['price']))} {Settings.DEFAULT_CURRENCY}",
            "Brand": product.get("vendor", ""),
            "MPN": variant.get("sku", ""),
            "Availability": "In Stock" if variant.get("available", False) else "Out of Stock",
            "Condition": "New",
            "Description": remove_html_tags(product.get("body_html", "")),
            "ProductType": product.get("product_type", ""),
            "ItemGroupID": str(product["id"])
        }

        # Přidání ceny před slevou, pokud existuje
        if variant.get("compare_at_price"):
            variant_data["SalePrice"] = f"{int(float(variant['compare_at_price']))} {Settings.DEFAULT_CURRENCY}"

        # Přidání váhy, pokud je k dispozici
        if variant.get("grams"):
            weight_kg = float(variant["grams"]) / 1000
            variant_data["ShippingWeight"] = f"{weight_kg:.2f} kg"

        # Přidání dodatečných obrázků
        if len(product.get("images", [])) > 1:
            variant_data["AdditionalImageLink"] = [img["src"] for img in product["images"][1:]]

        # Přidání dodacích možností
        for delivery_id, delivery_info in Settings.DEFAULT_SHIPPING.items():
            variant_data["Shipping"] = {
                "Service": delivery_id,
                "Country": delivery_info["country"],
                "Price": f"{delivery_info['price']} {Settings.DEFAULT_CURRENCY}"
            }

        # Přidání GTIN (EAN), pokud existuje
        if variant.get("barcode"):
            variant_data["GTIN"] = variant["barcode"]

        variants.append(variant_data)

    return variants

def create_xml_feed(products, base_url, output_path=None):
    """Create XML feed in Bing Shopping format."""
    # Získání informací o obchodu
    shop_info = get_shop_info(base_url)
    if not shop_info:
        logging.warning("Could not fetch shop information, using default values")
        shop_info = {
            "name": "E-shop",
            "description": "",  # Prázdný popis
            "url": base_url
        }

    # Vytvoření kořenového elementu
    root = ET.Element("Catalog")
    
    # Přidání informací o kanálu
    ET.SubElement(root, "Title").text = shop_info.get("name", "")
    ET.SubElement(root, "Description").text = ""  # Vždy prázdný popis
    ET.SubElement(root, "Link").text = shop_info.get("url", base_url)
    
    # Zpracování produktů
    for product in products:
        variants = process_product(product, base_url)
        for variant in variants:
            item = ET.SubElement(root, "Product")
            
            # Přidání všech polí do item elementu
            for key, value in variant.items():
                if isinstance(value, list):
                    for v in value:
                        ET.SubElement(item, key).text = v
                elif isinstance(value, dict):
                    shipping = ET.SubElement(item, key)
                    for k, v in value.items():
                        ET.SubElement(shipping, k).text = v
                else:
                    ET.SubElement(item, key).text = str(value)

    # Vytvoření XML souboru
    tree = ET.ElementTree(root)
    if output_path is None:
        os.makedirs(Settings.OUTPUT_FOLDER, exist_ok=True)
        output_path = os.path.join(Settings.OUTPUT_FOLDER, Settings.XML_FILENAME)
    else:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
    tree.write(output_path, encoding='utf-8', xml_declaration=True)
    return output_path

def create_xml_feed_from_store(store_url: str, output_path: str = None):
    """Vytvoří XML feed pro Bing Shopping z Shopify obchodu."""
    try:
        # Validace URL obchodu
        if not store_url.startswith(('http://', 'https://')):
            store_url = f"https://{store_url}"
        store_url = store_url.rstrip('/')
        
        # Získání všech produktů
        logging.info(f"Fetching products from {store_url}")
        products = get_products_pages(store_url)
        
        if not products:
            logging.warning("No products found")
            return None
        
        logging.info(f"Found {len(products)} products")
        
        # Vytvoření XML feedu
        if output_path is None:
            output_path = os.path.join(Settings.OUTPUT_FOLDER, Settings.XML_FILENAME)
        
        # Vytvoření feedu pomocí existující funkce
        feed_path = create_xml_feed(products, store_url, output_path)
        
        logging.info(f"Feed saved to {feed_path}")
        return feed_path
        
    except Exception as e:
        logging.error(f"Error creating Bing feed: {str(e)}")
        raise

def main():
    """Main function to run the feed generation."""
    # Nastavení logování
    logging.basicConfig(
        level=Settings.LOG_LEVEL,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Parsování argumentů
    parser = argparse.ArgumentParser(description='Generate Bing Shopping feed from Shopify store')
    parser.add_argument('url', help='Shopify store URL')
    parser.add_argument('--collection', help='Specific collection to process')
    args = parser.parse_args()

    # Validace URL
    base_url = validate_url(args.url)
    logging.info(f"Processing store: {base_url}")

    try:
        # Získání produktů
        if args.collection:
            logging.info(f"Processing collection: {args.collection}")
            products = get_collection_products(base_url, args.collection)
        else:
            logging.info("Processing all products")
            products = get_products_pages(base_url)

        if not products:
            logging.error("No products found")
            return

        logging.info(f"Found {len(products)} products")

        # Vytvoření XML feedu
        logging.info("Creating XML feed...")
        output_path = create_xml_feed(products, base_url)
        logging.info(f"Feed saved to {output_path}")

    except Exception as e:
        logging.error(f"Error: {str(e)}")
        raise

if __name__ == "__main__":
    main() 