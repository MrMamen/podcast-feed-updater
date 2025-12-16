#!/usr/bin/env python3
"""
Enrich cd SPILL feed for Spotify distribution.
Identical to main enriched feed but with separate output file for independent publishing.

This feed is identical to the main cdspill-enriched.xml feed and includes all
Podcasting 2.0 tags. It exists separately to allow independent manual publishing
to Spotify without affecting the main feed.

Usage:
    uv run enrich_cdspill_spotify.py                  # Fetch from online source
    uv run enrich_cdspill_spotify.py --local-cache    # Use local cached copy

Local cache:
    The --local-cache option uses a local copy of the feed for testing
    when the network is down or for faster development iterations.
    Download the cache with: uv run python3 download_cdspill_cache.py

Person data:
    - Permanent staff: cdspill_permanent_staff.json (hosts and other permanent roles)
    - Known guests: cdspill_known_guests.json (profile images, URLs, name aliases)
    - Auto-detection: Guests detected from episode titles ("med [name]")
    - Lookup new guests: uv run python3 lookup_guest.py "Guest Name"

The script adds:
    - Permanent hosts at channel level (with profile images and URLs)
    - Auto-detected guests per episode (with profile data where available)
    - Patreon funding link
    - Social interactions (Bluesky, Twitter/X, Facebook)
    - Season/episode numbering with Norwegian season names
    - OP3 analytics for privacy-respecting download tracking
    - Podlove Simple Chapters (converted from JSON)
"""

import os
import sys
import argparse
import requests
import shutil
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()


def main():
    """Generate Spotify feed (identical copy of enriched feed)."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Generate cd SPILL feed for Spotify (identical to main enriched feed)'
    )
    parser.add_argument(
        '--local-cache',
        action='store_true',
        help='Use local enriched feed instead of fetching from GitHub Pages'
    )
    args = parser.parse_args()

    print("="*60)
    print("CD SPILL SPOTIFY FEED GENERATOR")
    print("="*60)

    output_file = "docs/cdspill-spotify.xml"

    # Determine source
    if args.local_cache:
        # For local testing, copy the enriched feed that was generated
        source_file = "docs/cdspill-enriched.xml"
        if not os.path.exists(source_file):
            print(f"\n❌ Error: Enriched feed not found at {source_file}")
            print("   Run enrich_cdspill.py first to generate the enriched feed")
            sys.exit(1)
        print(f"\n📁 Using local enriched feed: {source_file}")

        # Create output directory
        os.makedirs("docs", exist_ok=True)

        # Simply copy the file
        shutil.copy2(source_file, output_file)
        print(f"✓ Copied enriched feed to: {output_file}")

    else:
        # Fetch from already enriched feed (deployed on GitHub Pages)
        source_url = "https://mrmamen.github.io/podcast-feed-updater/cdspill-enriched.xml"
        print(f"\n🌐 Fetching enriched feed from: {source_url}")

        # Fetch and save
        response = requests.get(source_url, timeout=30)
        response.raise_for_status()

        # Create output directory
        os.makedirs("docs", exist_ok=True)

        # Write content exactly as received (preserves all formatting and namespaces)
        with open(output_file, 'wb') as f:
            f.write(response.content)

        print(f"✓ Downloaded and saved to: {output_file}")

    print("\n" + "="*60)
    print("DONE!")
    print("="*60)
    print("\nSpotify feed: docs/cdspill-spotify.xml")
    print("\nThis feed is identical to the main enriched feed and includes:")
    print("  ✓ Permanent hosts with profile images and URLs")
    print("  ✓ Podcast GUID: Unique identifier for feed portability")
    print("  ✓ Season/episode tags with Norwegian season names")
    print("  ✓ Auto-detected guests with profile data")
    print("  ✓ Patreon funding link")
    print("  ✓ Podcasting 2.0 tags (medium, update frequency, podroll, social interactions)")
    print("  ✓ OP3 analytics for privacy-respecting download tracking")
    print("  ✓ Podlove Simple Chapters (inline chapter markers)")
    print("\nSource: Already enriched feed from GitHub Pages")
    print("Next steps:")
    print("  1. Review docs/cdspill-spotify.xml")
    print("  2. Upload to Spotify when ready")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
