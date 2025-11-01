"""
Bing Shopping feed generator.
"""

import os
import logging
import xml.etree.ElementTree as ET
from typing import List, Dict, Any
from urllib.parse import urljoin

from shopify_to_feeds.feeds.base import BaseFeedGenerator
from shopify_to_feeds.scraper.shopify_client import ShopifyClient
from shopify_to_feeds.utils.helpers import remove_html_tags


logger = logging.getLogger(__name__)


class BingFeedGenerator(BaseFeedGenerator):
    """
    Generator for Bing Shopping XML feeds.
    """

    DEFAULT_CURRENCY = "CZK"
    DEFAULT_SHIPPING = {
        "PPL": {
            "price": 0,
            "country": "CZ"
        }
    }

    def __init__(self, store_url: str, currency: str = DEFAULT_CURRENCY):
        """
        Initialize Bing feed generator.

        Args:
            store_url: Shopify store URL
            currency: Currency code (default: CZK)
        """
        super().__init__(store_url)
        self.currency = currency
        self.client = ShopifyClient(store_url)

    def get_feed_type(self) -> str:
        """Get feed type identifier."""
        return "bing"

    def _process_product(self, product: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Process a single product and return list of variant dictionaries.

        Args:
            product: Product dictionary from Shopify API

        Returns:
            List of variant dictionaries ready for XML generation
        """
        variants = []
        base_url = self.store_url

        for variant in product.get("variants", []):
            variant_data = {
                "ProductID": str(variant["id"]),
                "Title": (
                    f"{product['title']} - {variant['title']}"
                    if variant['title'] != "Default Title"
                    else product['title']
                ),
                "Link": urljoin(base_url, f"/products/{product['handle']}?variant={variant['id']}"),
                "ImageLink": product["images"][0]["src"] if product.get("images") else "",
                "Price": f"{int(float(variant['price']))} {self.currency}",
                "Brand": product.get("vendor", ""),
                "MPN": variant.get("sku", ""),
                "Availability": "In Stock" if variant.get("available", False) else "Out of Stock",
                "Condition": "New",
                "Description": remove_html_tags(product.get("body_html", "")),
                "ProductType": product.get("product_type", ""),
                "ItemGroupID": str(product["id"])
            }

            # Add sale price if available
            if variant.get("compare_at_price"):
                variant_data["SalePrice"] = f"{int(float(variant['compare_at_price']))} {self.currency}"

            # Add weight if available
            if variant.get("grams"):
                weight_kg = float(variant["grams"]) / 1000
                variant_data["ShippingWeight"] = f"{weight_kg:.2f} kg"

            # Add additional images
            if len(product.get("images", [])) > 1:
                variant_data["AdditionalImageLink"] = [img["src"] for img in product["images"][1:]]

            # Add shipping
            for delivery_id, delivery_info in self.DEFAULT_SHIPPING.items():
                variant_data["Shipping"] = {
                    "Service": delivery_id,
                    "Country": delivery_info["country"],
                    "Price": f"{delivery_info['price']} {self.currency}"
                }

            # Add GTIN if available
            if variant.get("barcode"):
                variant_data["GTIN"] = variant["barcode"]

            variants.append(variant_data)

        return variants

    def generate(self, output_path: str, **kwargs) -> str:
        """
        Generate Bing Shopping XML feed.

        Args:
            output_path: Path where feed file should be saved
            **kwargs: Additional parameters (ignored for Bing feed)

        Returns:
            Path to generated feed file
        """
        try:
            self.logger.info(f"Starting Bing feed generation for {self.store_url}")

            # Fetch all products
            all_variants = []
            for product in self.client.get_all_products():
                variants = self._process_product(product)
                all_variants.extend(variants)

            self.logger.info(f"Processed {len(all_variants)} product variants")

            # Get shop info
            shop_info = self.client.get_shop_info()
            if not shop_info:
                shop_info = {
                    "name": "E-shop",
                    "description": "",
                    "url": self.store_url
                }

            # Create XML structure
            root = ET.Element("Catalog")
            ET.SubElement(root, "Title").text = shop_info.get("name", "")
            ET.SubElement(root, "Description").text = ""
            ET.SubElement(root, "Link").text = shop_info.get("url", self.store_url)

            # Add products
            for variant in all_variants:
                item = ET.SubElement(root, "Product")

                for key, value in variant.items():
                    if isinstance(value, list):
                        for v in value:
                            ET.SubElement(item, key).text = str(v)
                    elif isinstance(value, dict):
                        shipping = ET.SubElement(item, key)
                        for k, v in value.items():
                            ET.SubElement(shipping, k).text = str(v)
                    else:
                        ET.SubElement(item, key).text = str(value)

            # Save XML file
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            tree = ET.ElementTree(root)
            tree.write(output_path, encoding='utf-8', xml_declaration=True)

            self.logger.info(f"Bing feed saved to {output_path}")
            self.logger.info(f"Feed generation completed: {len(all_variants)} products")
            return output_path

        except Exception as e:
            self.logger.error(f"Error generating Bing feed: {str(e)}")
            raise

