import json
import requests
import logging
from urllib.parse import urljoin
import argparse
from pprint import pprint


def validate_url(url):
    """Validate and correct URL format."""
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url.rstrip('/')


def make_request(url, headers=None):
    """Make a GET request to the Shopify API."""
    if headers is None:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36"
        }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logging.error(f"Request failed: {e}")
        return None


def explore_product_data(url):
    """Explore all available product data from the first product."""
    products_url = urljoin(url, "/products.json?limit=1")
    data = make_request(products_url)
    
    if not data or not data.get("products"):
        print("No products found!")
        return
    
    product = data["products"][0]
    print("\n=== PRODUCT DATA STRUCTURE ===")
    print("\nTop-level fields:")
    for key in product.keys():
        print(f"- {key}")
    
    print("\n=== VARIANT DATA STRUCTURE ===")
    if product.get("variants"):
        variant = product["variants"][0]
        print("\nVariant fields:")
        for key in variant.keys():
            print(f"- {key}")
    
    print("\n=== OPTION DATA STRUCTURE ===")
    if product.get("options"):
        option = product["options"][0]
        print("\nOption fields:")
        for key in option.keys():
            print(f"- {key}")
    
    print("\n=== IMAGE DATA STRUCTURE ===")
    if product.get("images"):
        image = product["images"][0]
        print("\nImage fields:")
        for key in image.keys():
            print(f"- {key}")


def explore_collection_data(url):
    """Explore all available collection data."""
    collections_url = urljoin(url, "/collections.json?limit=1")
    data = make_request(collections_url)
    
    if not data or not data.get("collections"):
        print("No collections found!")
        return
    
    collection = data["collections"][0]
    print("\n=== COLLECTION DATA STRUCTURE ===")
    print("\nCollection fields:")
    for key in collection.keys():
        print(f"- {key}")


def explore_shop_data(url):
    """Explore shop metadata."""
    shop_url = urljoin(url, "/shop.json")
    data = make_request(shop_url)
    
    if not data or not data.get("shop"):
        print("No shop data found!")
        return
    
    shop = data["shop"]
    print("\n=== SHOP DATA STRUCTURE ===")
    print("\nShop fields:")
    for key in shop.keys():
        print(f"- {key}")


def main():
    parser = argparse.ArgumentParser(description="Explore Shopify store data structure")
    parser.add_argument("url", help="URL of the Shopify store")
    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    # Validate URL
    base_url = validate_url(args.url)
    print(f"\nExploring data from: {base_url}")

    # Explore different data types
    explore_product_data(base_url)
    explore_collection_data(base_url)
    explore_shop_data(base_url)


if __name__ == "__main__":
    main() 