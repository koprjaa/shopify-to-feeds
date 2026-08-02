#!/usr/bin/env python3
#
# Project: shopify-to-feeds
# File:    smoke_feeds.py
#
# Description:
# Manual end to end run that builds all three feeds against a live store.
#
# Author:
# Jan Alexandr Kopřiva
# jan.alexandr.kopriva@gmail.com
#
# License: MIT
#

"""Build every feed against a real store and report what came out.

This is a smoke run, not a test. It talks to a live shop, so it is never part of
the suite, and the file is not named test_* for that reason: pytest collecting
it would put the network in CI.

The store is an argument. It used to be hard coded to listnato.cz, which has
since stopped resolving, so the script tested nothing and said so in a way that
looked like a product bug.

    python smoke_feeds.py https://shop.example.com
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shopify_to_feeds.feeds import BingFeedGenerator, GoogleFeedGenerator, ZboziFeedGenerator
from shopify_to_feeds.feeds.base import EmptyFeedError

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

GENERATORS = {
    "google": GoogleFeedGenerator,
    "bing": BingFeedGenerator,
    "zbozi": ZboziFeedGenerator,
}


def build(name: str, store_url: str, output_dir: Path) -> bool:
    """Build one feed. True when a non-empty file came out of it."""
    logger.info("%s", "=" * 60)
    logger.info("Building the %s feed", name)
    generator = GENERATORS[name](store_url)
    output_path = output_dir / f"{name}_feed.xml"
    try:
        result = Path(generator.generate(str(output_path)))
    except EmptyFeedError as exc:
        logger.error("%s feed: %s", name, exc)  # noqa: TRY400 - the reason is the message
        return False
    except Exception:
        logger.exception("%s feed failed", name)
        return False

    if not result.exists():
        logger.error("%s feed: generate() returned %s but no file is there", name, result)
        return False
    logger.info("%s feed: %s (%s bytes)", name, result, f"{result.stat().st_size:,}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("store_url", help="Shopify store URL, for example https://shop.example.com")
    parser.add_argument("-o", "--output-dir", default="smoke_feeds_out", help="Where to write the feeds")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {name: build(name, args.store_url, output_dir) for name in GENERATORS}

    logger.info("%s", "=" * 60)
    for name, ok in results.items():
        logger.info("%-8s %s", name, "built" if ok else "failed")

    failed = [name for name, ok in results.items() if not ok]
    if failed:
        logger.error("%d of %d feeds failed: %s", len(failed), len(results), ", ".join(failed))
        return 1
    logger.info("All %d feeds built", len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
