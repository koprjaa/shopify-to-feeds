"""
Helper utility functions.
"""

import re
from typing import Optional


def remove_html_tags(text: Optional[str], max_length: Optional[int] = None) -> str:
    """
    Remove HTML tags from text and optionally limit length.

    Args:
        text: Text with HTML tags
        max_length: Maximum length of cleaned text (None for no limit)

    Returns:
        Cleaned text without HTML tags
    """
    if not text:
        return ""

    cleaned = re.sub(r'<[^>]+>', '', str(text))
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    if max_length and len(cleaned) > max_length:
        cleaned = cleaned[:max_length]

    return cleaned


def format_price(price: str, currency: str = "CZK") -> str:
    """
    Format price with currency.

    Args:
        price: Price value as string
        currency: Currency code

    Returns:
        Formatted price string
    """
    try:
        return f"{float(price):.2f} {currency}"
    except (ValueError, TypeError):
        return f"0.00 {currency}"


def format_weight(grams: Optional[float], unit: str = "kg") -> Optional[str]:
    """
    Convert grams to specified unit and format weight.

    Args:
        grams: Weight in grams
        unit: Target unit (kg, g, etc.)

    Returns:
        Formatted weight string or None if grams is None
    """
    if not grams:
        return None

    if unit == "kg":
        return f"{float(grams) / 1000:.3f} {unit}"
    return f"{float(grams)} {unit}"

