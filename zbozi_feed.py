import time
import re
import os
import logging
import requests
import argparse
import xml.etree.ElementTree as ET
import concurrent.futures
from urllib.parse import urljoin, urlparse
from datetime import datetime

class Settings:
    """Application settings."""
    OUTPUT_FOLDER = "zbozi_feed_exports"
    XML_FILENAME = "zbozi_products.xml"
    LOG_FILENAME = "zbozi_feed.log"
    MAX_RETRIES = 3
    RETRY_DELAY = 180  # 3 minutes
    LOG_LEVEL = logging.INFO
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    DEFAULT_DELIVERY = {
        "ZASILKOVNA": {"price": 59, "cod_price": 0},
        "PPL": {"price": 59, "cod_price": 0}
    }
    DEFAULT_DELIVERY_DATE = 3

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
    """Validate and fix URL format."""
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url.rstrip('/')

def make_request(url, retry_count=0):
    """Make a GET request with retry logic."""
    try:
        response = requests.get(url, headers={"User-Agent": Settings.USER_AGENT})
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        if retry_count < Settings.MAX_RETRIES:
            logging.warning(f"Request failed: {str(e)}. Retrying in {Settings.RETRY_DELAY} seconds...")
            time.sleep(Settings.RETRY_DELAY)
            return make_request(url, retry_count + 1)
        else:
            logging.error(f"Request failed after {Settings.MAX_RETRIES} retries: {str(e)}")
            return None

def get_page(url, page=1, collection=None):
    """Get a page of products from Shopify store."""
    if collection:
        url = f"{url}/collections/{collection}/products.json?page={page}"
    else:
        url = f"{url}/products.json?page={page}"
    return make_request(url)

def get_page_collections(url):
    """Get all collections from Shopify store."""
    page = 1
    while True:
        url = f"{url}/collections.json?page={page}"
        data = make_request(url)
        if not data or not data.get("collections"):
            break
        for collection in data["collections"]:
            yield collection
        page += 1

def extract_products_collection(url, collection=None):
    """Extract all products from a collection."""
    page = 1
    while True:
        data = get_page(url, page, collection)
        if not data or not data.get("products"):
            break
        for product in data["products"]:
            yield product
        page += 1

def setup_output_folders():
    """Create necessary output folders if they don't exist."""
    os.makedirs(Settings.OUTPUT_FOLDER, exist_ok=True)

def process_product(product, base_url):
    """Process a single product and its variants."""
    variants = []
    for variant in product["variants"]:
        # Základní data produktu
        variant_data = {
            # Povinné tagy
            "PRODUCTNAME": f"{product['title']} - {variant['title']}" if variant['title'] != "Default Title" else product['title'],
            "DESCRIPTION": remove_html_tags(product.get("body_html", "")),
            "URL": urljoin(base_url, f"/products/{product['handle']}?variant={variant['id']}"),
            "PRICE_VAT": str(int(float(variant["price"]))),
            "DELIVERY_DATE": str(Settings.DEFAULT_DELIVERY_DATE),
            "IMGURL": product["images"][0]["src"] if product.get("images") else "",
            "ITEM_ID": str(variant["id"]),
            "ITEMGROUP_ID": str(product["id"]),
            
            # Doporučené tagy
            "PRODUCT": product['title'],
            "MANUFACTURER": product.get("vendor", ""),
            "CATEGORYTEXT": " | ".join(product.get("product_type", "").split("/")),
            "EAN": variant.get("barcode", ""),
            "PRODUCTNO": variant.get("sku", "") or f"MM-{product['handle'][:10].upper()}",
            "CONDITION": "new",
            "BRAND": product.get("vendor", ""),
            
            # Doplňkové tagy
            "WARRANTY": "24",  # 24 měsíců záruka
            "VISIBILITY": "1",  # Nabídka je viditelná
            "CUSTOM_LABEL_0": "Listnato",  # Vlastní označení
            "CUSTOM_LABEL_1": product.get("product_type", ""),  # Typ produktu
            "CUSTOM_LABEL_2": " | ".join(product.get("tags", []))  # Tagy produktu
        }

        # Přidání ceny před slevou, pokud existuje
        if variant.get("compare_at_price"):
            variant_data["PRICE_BEFORE_DISCOUNT"] = str(int(float(variant["compare_at_price"])))

        # Přidání dodatečných obrázků
        if len(product.get("images", [])) > 1:
            for img in product["images"][1:]:
                if "IMGURL_ALTERNATIVE" not in variant_data:
                    variant_data["IMGURL_ALTERNATIVE"] = []
                variant_data["IMGURL_ALTERNATIVE"].append(img["src"])

        # Přidání dodacích možností
        for delivery_id, delivery_info in Settings.DEFAULT_DELIVERY.items():
            delivery = {
                "DELIVERY_ID": delivery_id,
                "DELIVERY_PRICE": str(delivery_info["price"]),
                "DELIVERY_PRICE_COD": str(delivery_info["cod_price"])
            }
            variant_data["DELIVERY"] = delivery

        # Přidání parametrů produktu
        params = []
        
        # Přidání variant jako parametrů
        if variant.get("option1"):
            params.append({
                "PARAM_NAME": product["options"][0]["name"] if product.get("options") else "Variant",
                "VAL": variant["option1"]
            })
        if variant.get("option2"):
            params.append({
                "PARAM_NAME": product["options"][1]["name"] if len(product.get("options", [])) > 1 else "Variant 2",
                "VAL": variant["option2"]
            })
        if variant.get("option3"):
            params.append({
                "PARAM_NAME": product["options"][2]["name"] if len(product.get("options", [])) > 2 else "Variant 3",
                "VAL": variant["option3"]
            })

        # Přidání váhy, pokud je k dispozici
        if variant.get("grams"):
            weight_kg = float(variant["grams"]) / 1000
            params.append({
                "PARAM_NAME": "Hmotnost",
                "VAL": f"{weight_kg:.2f} kg"
            })

        # Přidání dostupnosti
        if variant.get("available") is not None:
            params.append({
                "PARAM_NAME": "Dostupnost",
                "VAL": "Skladem" if variant["available"] else "Není skladem"
            })

        # Přidání průměru květináče, pokud je v názvu
        pot_size = re.search(r'(\d+)\s*cm', variant_data["PRODUCTNAME"])
        if pot_size:
            params.append({
                "PARAM_NAME": "Průměr květináče",
                "VAL": f"{pot_size.group(1)} cm"
            })

        variant_data["PARAM"] = params
        variants.append(variant_data)

    return variants

def process_collection(url, collection=None):
    """Process all products in a collection."""
    products = []
    for product in extract_products_collection(url, collection):
        products.extend(process_product(product, url))
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

def create_xml_feed(products, base_url, output_path=None):
    """Create XML feed in Zbozi format."""
    # Získání informací o obchodu
    shop_info = get_shop_info(base_url)
    if not shop_info:
        logging.warning("Could not fetch shop information, using default values")
        shop_info = {
            "name": "E-shop",
            "description": "",
            "url": base_url
        }

    # Vytvoření kořenového elementu
    root = ET.Element("SHOP")
    
    # Přidání informací o kanálu
    ET.SubElement(root, "SHOP_NAME").text = shop_info.get("name", "")
    ET.SubElement(root, "SHOP_DESCRIPTION").text = ""  # Vždy prázdný popis
    ET.SubElement(root, "SHOP_URL").text = shop_info.get("url", base_url)
    
    # Zpracování produktů
    for product in products:
        variants = process_product(product, base_url)
        for variant in variants:
            item = ET.SubElement(root, "SHOPITEM")
            
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
    """Vytvoří XML feed pro Zbozi z Shopify obchodu."""
    try:
        # Validace URL obchodu
        if not store_url.startswith(('http://', 'https://')):
            store_url = f"https://{store_url}"
        store_url = store_url.rstrip('/')
        
        # Získání všech kolekcí
        logging.info(f"Fetching collections from {store_url}")
        collections = list(get_page_collections(store_url))
        
        # Získání produktů z kolekcí
        all_products = []
        for collection in collections:
            logging.info(f"Processing collection: {collection['handle']}")
            products = list(extract_products_collection(store_url, collection['handle']))
            all_products.extend(products)
        
        if not all_products:
            logging.warning("No products found")
            return None
        
        logging.info(f"Found {len(all_products)} products")
        
        # Vytvoření XML feedu
        if output_path is None:
            output_path = os.path.join(Settings.OUTPUT_FOLDER, Settings.XML_FILENAME)
        
        # Vytvoření feedu pomocí existující funkce
        feed_path = create_xml_feed(all_products, store_url, output_path)
        
        logging.info(f"Feed saved to {feed_path}")
        return feed_path
        
    except Exception as e:
        logging.error(f"Error creating Zbozi feed: {str(e)}")
        raise

def main():
    parser = argparse.ArgumentParser(description="Generate zbozi.cz feed from Shopify store")
    parser.add_argument("url", help="Shopify store URL")
    parser.add_argument("--collections", nargs="+", help="Specific collections to process")
    parser.add_argument("--workers", type=int, default=4, help="Number of worker threads")
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=Settings.LOG_LEVEL,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Validate and fix URL
    base_url = validate_url(args.url)
    logging.info(f"Processing store: {base_url}")

    # Setup output folders
    setup_output_folders()
    output_path = os.path.join(Settings.OUTPUT_FOLDER, Settings.XML_FILENAME)

    # Process products
    all_products = []
    if args.collections:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_to_collection = {
                executor.submit(process_collection, base_url, collection): collection
                for collection in args.collections
            }
            for future in concurrent.futures.as_completed(future_to_collection):
                collection = future_to_collection[future]
                try:
                    products = future.result()
                    all_products.extend(products)
                    logging.info(f"Processed collection {collection}: {len(products)} products")
                except Exception as e:
                    logging.error(f"Error processing collection {collection}: {str(e)}")
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_to_collection = {
                executor.submit(process_collection, base_url): "all"
            }
            for future in concurrent.futures.as_completed(future_to_collection):
                try:
                    products = future.result()
                    all_products.extend(products)
                    logging.info(f"Processed all products: {len(products)} products")
                except Exception as e:
                    logging.error(f"Error processing products: {str(e)}")

    # Create XML feed
    create_xml_feed(all_products, base_url)

if __name__ == "__main__":
    main() 