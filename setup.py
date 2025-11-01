"""
Setup script for shopify-to-feeds package.
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="shopify-to-feeds",
    version="1.0.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="Universal tool for generating product feeds from Shopify stores",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/koprjaa/shopify-to-feeds",
    packages=find_packages(exclude=["tests", "*.tests", "*.tests.*", "tests.*"]),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "shopify-feeds-api=shopify_to_feeds.api:app",
        ],
    },
)

