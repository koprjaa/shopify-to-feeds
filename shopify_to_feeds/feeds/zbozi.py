"""
Zbozi.cz feed generator.
"""

import os
import re
import logging
import xml.etree.ElementTree as ET
from typing import List, Dict, Any
from urllib.parse import urljoin

from shopify_to_feeds.feeds.base import BaseFeedGenerator
from shopify_to_feeds.scraper.shopify_client import ShopifyClient
from shopify_to_feeds.utils.helpers import remove_html_tags


logger = logging.getLogger(__name__)


class ZboziFeedGenerator(BaseFeedGenerator):
    """
    Generator for Zbozi.cz XML feeds.
    """

    DEFAULT_DELIVERY = {
        "ZASILKOVNA": {"price": 59, "cod_price": 0},
        "PPL": {"price": 59, "cod_price": 0}
    }
    DEFAULT_DELIVERY_DATE = 3

    def __init__(self, store_url: str):
        """
        Initialize Zbozi feed generator.

        Args:
            store_url: Shopify store URL
        """
        super().__init__(store_url)
        self.client = ShopifyClient(store_url)

    def get_feed_type(self) -> str:
        """Get feed type identifier."""
        return "zbozi"

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
                # Required fields
                "PRODUCTNAME": (
                    f"{product['title']} - {variant['title']}"
                    if variant['title'] != "Default Title"
                    else product['title']
                ),
                "DESCRIPTION": remove_html_tags(product.get("body_html", "")),
                "URL": urljoin(base_url, f"/products/{product['handle']}?variant={variant['id']}"),
                "PRICE_VAT": str(int(float(variant["price"]))),
                "DELIVERY_DATE": str(self.DEFAULT_DELIVERY_DATE),
                "IMGURL": product["images"][0]["src"] if product.get("images") else "",
                "ITEM_ID": str(variant["id"]),
                "ITEMGROUP_ID": str(product["id"]),

                # Recommended fields
                "PRODUCT": product['title'],
                "MANUFACTURER": product.get("vendor", ""),
                "CATEGORYTEXT": " | ".join(product.get("product_type", "").split("/")),
                "EAN": variant.get("barcode", ""),
                "PRODUCTNO": variant.get("sku", "") or f"MM-{product['handle'][:10].upper()}",
                "CONDITION": "new",
                "BRAND": product.get("vendor", ""),

                # Additional fields
                "WARRANTY": "24",
                "VISIBILITY": "1",
                "CUSTOM_LABEL_0": "Shopify",
                "CUSTOM_LABEL_1": product.get("product_type", ""),
                "CUSTOM_LABEL_2": " | ".join(product.get("tags", []))
            }

            # Add price before discount if available
            if variant.get("compare_at_price"):
                variant_data["PRICE_BEFORE_DISCOUNT"] = str(int(float(variant["compare_at_price"])))

            # Add additional images
            if len(product.get("images", [])) > 1:
                variant_data["IMGURL_ALTERNATIVE"] = [
                    img["src"] for img in product["images"][1:]
                ]

            # Add delivery options
            for delivery_id, delivery_info in self.DEFAULT_DELIVERY.items():
                variant_data["DELIVERY"] = {
                    "DELIVERY_ID": delivery_id,
                    "DELIVERY_PRICE": str(delivery_info["price"]),
                    "DELIVERY_PRICE_COD": str(delivery_info["cod_price"])
                }

            # Add product parameters
            params = []

            # Add variant options as parameters
            if variant.get("option1"):
                params.append({
                    "PARAM_NAME": (
                        product["options"][0]["name"]
                        if product.get("options")
                        else "Variant"
                    ),
                    "VAL": variant["option1"]
                })
            if variant.get("option2"):
                params.append({
                    "PARAM_NAME": (
                        product["options"][1]["name"]
                        if len(product.get("options", [])) > 1
                        else "Variant 2"
                    ),
                    "VAL": variant["option2"]
                })
            if variant.get("option3"):
                params.append({
                    "PARAM_NAME": (
                        product["options"][2]["name"]
                        if len(product.get("options", [])) > 2
                        else "Variant 3"
                    ),
                    "VAL": variant["option3"]
                })

            # Add weight if available
            if variant.get("grams"):
                weight_kg = float(variant["grams"]) / 1000
                params.append({
                    "PARAM_NAME": "Hmotnost",
                    "VAL": f"{weight_kg:.2f} kg"
                })

            # Add availability
            if variant.get("available") is not None:
                params.append({
                    "PARAM_NAME": "Dostupnost",
                    "VAL": "Skladem" if variant["available"] else "Není skladem"
                })

            # Extract pot size if in product name
            pot_size = re.search(r'(\d+)\s*cm', variant_data["PRODUCTNAME"])
            if pot_size:
                params.append({
                    "PARAM_NAME": "Průměr květináče",
                    "VAL": f"{pot_size.group(1)} cm"
                })

            variant_data["PARAM"] = params
            variants.append(variant_data)

        return variants

    def generate(self, output_path: str, **kwargs) -> str:
        """
        Generate Zbozi.cz XML feed.

        Args:
            output_path: Path where feed file should be saved
            **kwargs: Additional parameters (ignored for Zbozi feed)

        Returns:
            Path to generated feed file
        """
        try:
            self.logger.info(f"Starting Zbozi feed generation for {self.store_url}")

            # Fetch all collections and products
            all_variants = []
            collections = list(self.client.get_collections())

            for collection in collections:
                try:
                    self.logger.info(f"Processing collection: {collection['title']}")
                    for product in self.client.get_collection_products(collection["handle"]):
                        variants = self._process_product(product)
                        all_variants.extend(variants)
                except Exception as e:
                    self.logger.error(f"Error processing collection {collection['handle']}: {str(e)}")
                    continue

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
            root = ET.Element("SHOP")
            ET.SubElement(root, "SHOP_NAME").text = shop_info.get("name", "")
            ET.SubElement(root, "SHOP_DESCRIPTION").text = ""
            ET.SubElement(root, "SHOP_URL").text = shop_info.get("url", self.store_url)

            # Add products
            for variant in all_variants:
                item = ET.SubElement(root, "SHOPITEM")

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

            self.logger.info(f"Zbozi feed saved to {output_path}")
            self.logger.info(f"Feed generation completed: {len(all_variants)} products")
            return output_path

        except Exception as e:
            self.logger.error(f"Error generating Zbozi feed: {str(e)}")
            raise

