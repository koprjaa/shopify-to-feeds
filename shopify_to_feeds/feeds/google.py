"""
Google Merchant Center feed generator.
"""

import os
import logging
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin

from shopify_to_feeds.feeds.base import BaseFeedGenerator
from shopify_to_feeds.scraper.shopify_client import ShopifyClient
from shopify_to_feeds.scraper.image_downloader import ImageDownloader
from shopify_to_feeds.utils.helpers import remove_html_tags, format_price


logger = logging.getLogger(__name__)


class GoogleFeedGenerator(BaseFeedGenerator):
    """
    Generator for Google Merchant Center XML feeds.
    """

    DEFAULT_CURRENCY = "CZK"
    DEFAULT_SHIPPING = {
        "country": "CZ",
        "service": "Standard",
        "price": "0 CZK",
        "carrier_shipping": "true",
        "shipping_transit_business_days": "2"
    }
    DEFAULT_TAX = {
        "country": "CZ",
        "rate": "21.0",
        "tax_ship": "y"
    }

    def __init__(
        self,
        store_url: str,
        currency: str = DEFAULT_CURRENCY,
        download_images: bool = False,
        max_workers: int = 4
    ):
        """
        Initialize Google feed generator.

        Args:
            store_url: Shopify store URL
            currency: Currency code (default: CZK)
            download_images: Whether to download product images
            max_workers: Number of parallel workers for image downloads
        """
        super().__init__(store_url)
        self.currency = currency
        self.download_images = download_images
        self.max_workers = max_workers
        self.client = ShopifyClient(store_url)
        self.image_downloader = ImageDownloader(max_workers=max_workers) if download_images else None

    def get_feed_type(self) -> str:
        """Get feed type identifier."""
        return "google"

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

        # Get product images
        image_links = []
        if "images" in product and product["images"]:
            image_links = [img["src"] for img in product["images"]]
        elif "image" in product:
            image_links = [product["image"]["src"]]

        product_type = product.get("product_type", "")
        product_tags = product.get("tags", "")

        # Process each variant
        for variant in product.get("variants", []):
            try:
                variant_id = variant.get("id", "")
                variant_title = variant.get("title", "Default Title")
                variant_sku = variant.get("sku", "")
                variant_price = variant.get("price", "0.0")
                variant_available = variant.get("available", False)

                variant_data = {
                    "id": str(variant_id),
                    "title": f"{product.get('title', '')} - {variant_title}".replace(" - Default Title", ""),
                    "description": remove_html_tags(product.get("body_html", ""), max_length=5000),
                    "link": urljoin(base_url, f"/products/{product.get('handle', '')}"),
                    "image_link": image_links[0] if image_links else "",
                    "availability": "in stock" if variant_available else "out of stock",
                    "price": format_price(variant_price, self.currency),
                    "brand": product.get("vendor", ""),
                    "condition": "new",
                    "google_product_category": product_tags if product_tags else "Home & Garden",
                }

                # Add optional fields
                if product_type:
                    variant_data["product_type"] = product_type
                if variant_sku:
                    variant_data["gtin"] = variant_sku
                    variant_data["mpn"] = variant_sku
                if len(image_links) > 1:
                    variant_data["additional_image_link"] = image_links[1:]

                variants.append(variant_data)
            except Exception as e:
                self.logger.error(f"Error processing variant {variant.get('id', 'unknown')}: {str(e)}")
                continue

        return variants

    def generate(self, output_path: str, **kwargs) -> str:
        """
        Generate Google Merchant Center XML feed.

        Args:
            output_path: Path where feed file should be saved
            **kwargs: Additional parameters (ignored for Google feed)

        Returns:
            Path to generated feed file
        """
        try:
            self.logger.info(f"Starting Google feed generation for {self.store_url}")

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

            # Download images if requested
            if self.download_images and self.image_downloader and all_variants:
                from datetime import datetime
                from urllib.parse import urlparse

                parsed_url = urlparse(self.store_url)
                store_name = parsed_url.netloc.split(".")[0]
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                images_folder = os.path.join(
                    os.path.dirname(output_path),
                    f"{store_name}_images_{timestamp}"
                )

                self.logger.info(f"Starting image download to folder: {images_folder}")
                self.image_downloader.download_product_images(
                    all_variants,
                    images_folder,
                    image_field="image_link"
                )

            # Get shop info
            shop_info = self.client.get_shop_info()
            if not shop_info:
                shop_info = {
                    "name": "E-shop",
                    "description": "",
                    "url": self.store_url
                }

            # Register namespace
            ET.register_namespace('g', 'http://base.google.com/ns/1.0')

            # Create XML structure
            root = ET.Element("rss", {
                "version": "2.0",
                "xmlns:g": "http://base.google.com/ns/1.0"
            })

            channel = ET.SubElement(root, "channel")
            ET.SubElement(channel, "title").text = shop_info["name"]
            ET.SubElement(channel, "link").text = shop_info["url"]
            ET.SubElement(channel, "description").text = shop_info["description"]

            # Add products
            for variant in all_variants:
                item = ET.SubElement(channel, "item")

                # Required fields
                g_ns = "{http://base.google.com/ns/1.0}"
                ET.SubElement(item, f"{g_ns}id").text = str(variant["id"])
                ET.SubElement(item, f"{g_ns}title").text = variant["title"]
                ET.SubElement(item, f"{g_ns}description").text = variant["description"]
                ET.SubElement(item, f"{g_ns}link").text = variant["link"]
                ET.SubElement(item, f"{g_ns}image_link").text = variant["image_link"]
                ET.SubElement(item, f"{g_ns}availability").text = variant["availability"]
                ET.SubElement(item, f"{g_ns}price").text = variant["price"]
                ET.SubElement(item, f"{g_ns}brand").text = variant["brand"]
                ET.SubElement(item, f"{g_ns}condition").text = variant["condition"]
                ET.SubElement(item, f"{g_ns}google_product_category").text = variant["google_product_category"]

                # Optional fields
                if "gtin" in variant:
                    ET.SubElement(item, f"{g_ns}gtin").text = variant["gtin"]
                if "mpn" in variant:
                    ET.SubElement(item, f"{g_ns}mpn").text = variant["mpn"]
                if "product_type" in variant:
                    ET.SubElement(item, f"{g_ns}product_type").text = variant["product_type"]
                if "additional_image_link" in variant:
                    for img_url in variant["additional_image_link"]:
                        ET.SubElement(item, f"{g_ns}additional_image_link").text = img_url

            # Save XML file
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            tree = ET.ElementTree(root)
            tree.write(output_path, encoding="utf-8", xml_declaration=True)

            self.logger.info(f"Google feed saved to {output_path}")
            self.logger.info(f"Feed generation completed: {len(all_variants)} products")
            return output_path

        except Exception as e:
            self.logger.error(f"Error generating Google feed: {str(e)}")
            raise

