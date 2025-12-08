#!/usr/bin/env python3
"""
Download and cache the cd SPILL feed for local testing.

This script downloads the original Podbean feed and saves it locally.
This is useful for testing the enrichment script when the network is down
or for faster development iterations without repeatedly hitting the live feed.

Usage:
    uv run python3 download_cdspill_cache.py

The cached feed will be saved to: .cache/cdspill-original.xml

Note: This is for local development only. The GitHub Action workflow
      should always fetch from the live feed URL.
"""

import os
import sys
import requests
from datetime import datetime


def main():
    """Download and cache the cd SPILL feed."""
    feed_url = "https://feed.podbean.com/cdspill/feed.xml"
    cache_dir = ".cache"
    cache_file = os.path.join(cache_dir, "cdspill-original.xml")

    print("="*60)
    print("CD SPILL FEED CACHE DOWNLOADER")
    print("="*60)
    print(f"\nSource: {feed_url}")
    print(f"Destination: {cache_file}")

    # Create cache directory if it doesn't exist
    os.makedirs(cache_dir, exist_ok=True)

    # Download feed
    print("\nDownloading feed...")
    try:
        response = requests.get(feed_url, timeout=30)
        response.raise_for_status()

        # Save to cache file
        with open(cache_file, 'wb') as f:
            f.write(response.content)

        # Get file size
        file_size = os.path.getsize(cache_file)
        file_size_kb = file_size / 1024

        print(f"✓ Downloaded {file_size_kb:.1f} KB")
        print(f"✓ Cached to: {cache_file}")
        print(f"✓ Cached at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        print("\n" + "="*60)
        print("Cache ready!")
        print("="*60)
        print("\nYou can now run the enricher with local cache:")
        print("  uv run enrich_cdspill.py --local-cache")
        print("\nRemember: This is for local development only.")
        print("The GitHub Action should always use the live feed URL.")
        print()

    except requests.RequestException as e:
        print(f"\n❌ Error downloading feed: {e}")
        sys.exit(1)
    except IOError as e:
        print(f"\n❌ Error writing cache file: {e}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
