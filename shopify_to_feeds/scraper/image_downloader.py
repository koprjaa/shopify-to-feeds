#
# Project: shopify-to-feeds
# File:    image_downloader.py
#
# Description:
# Downloads product images and stores them next to the generated feed.
#
# Author:
# Jan Alexandr Kopřiva
# jan.alexandr.kopriva@gmail.com
#
# License: MIT
#

"""
Image downloader for product images.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from shopify_to_feeds.security import UrlValidationError, validate_image_url

logger = logging.getLogger(__name__)


class ImageDownloader:
    """
    Downloads product images from URLs.
    """

    def __init__(self, max_workers: int = 4):
        """
        Initialize image downloader.

        Args:
            max_workers: Maximum number of parallel download workers
        """
        self.max_workers = max_workers
        self.logger = logging.getLogger(self.__class__.__name__)

    def download_image(self, url: str, folder_path: str) -> str | None:
        """
        Download a single image from URL.

        Args:
            url: Image URL
            folder_path: Folder where image should be saved

        Returns:
            Filename of downloaded image or None if failed
        """
        if not url:
            return None

        # SSRF guard: reject non-http(s) schemes and hosts that resolve to
        # private, loopback or reserved addresses.
        try:
            validate_image_url(url)
        except UrlValidationError as e:
            self.logger.warning("Rejected image URL %r: %s", url, e)
            return None

        try:
            response = requests.get(url, timeout=30, allow_redirects=False)
            response.raise_for_status()
            filename = Path(urlparse(url).path).name
            if not filename:
                filename = f"image_{hash(url) % 10000}.jpg"

            filepath = str(Path(folder_path) / filename)
            Path(folder_path).mkdir(parents=True, exist_ok=True)

            with Path(filepath).open("wb") as f:
                f.write(response.content)

            self.logger.debug(f"Downloaded image: {filename}")
            return filename
        except requests.RequestException:
            self.logger.exception(f"Error downloading image from {url}")
            return None

    def download_product_images(
        self,
        products: list[dict[str, Any]],
        images_folder: str,
        image_field: str = "image_link"
    ) -> dict[str, str]:
        """
        Download images for multiple products.

        Args:
            products: List of product dictionaries
            images_folder: Folder where images should be saved
            image_field: Field name containing image URL

        Returns:
            Dictionary mapping image URLs to downloaded filenames
        """
        if not Path(images_folder).exists():
            Path(images_folder).mkdir(parents=True, exist_ok=True)
            self.logger.info(f"Created images folder: {images_folder}")

        downloaded_images = {}

        # Collect all unique image URLs
        image_urls = set()
        for product in products:
            if product.get(image_field):
                image_urls.add(product[image_field])
            if "additional_image_link" in product:
                for img_url in product["additional_image_link"]:
                    image_urls.add(img_url)

        total_images = len(image_urls)
        self.logger.info(f"Found {total_images} unique images to download")

        if total_images == 0:
            self.logger.info("No images found to download")
            return downloaded_images

        # Download images using ThreadPoolExecutor for parallel processing
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_url = {
                executor.submit(self.download_image, url, images_folder): url
                for url in image_urls
            }

            for i, future in enumerate(as_completed(future_to_url), 1):
                url = future_to_url[future]
                try:
                    filename = future.result()
                    if filename:
                        downloaded_images[url] = filename
                        self.logger.debug(f"Downloaded image: {filename}")

                    if i % 10 == 0 or i == total_images:
                        self.logger.info(f"Downloaded {i}/{total_images} images")
                except Exception:
                    self.logger.exception(f"Error downloading image from {url}")

        self.logger.info(
            f"Image download completed. Downloaded {len(downloaded_images)} images"
        )
        return downloaded_images

