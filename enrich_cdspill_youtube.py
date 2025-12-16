#!/usr/bin/env python3
"""
Enrich cd SPILL feed for YouTube distribution.
Based on main enriched feed with modifications for YouTube compatibility:
  - Episode numbers are restored to titles (e.g., "OutRun med Mats Lindh (#123)")
  - Chapter timestamps are added to descriptions (YouTube-compatible format)

YouTube doesn't support Podcasting 2.0 tags like psc:chapters, but it does
support timestamps in the description text. This script generates a feed
optimized for YouTube's requirements.

Usage:
    uv run enrich_cdspill_youtube.py                  # Fetch from online source
    uv run enrich_cdspill_youtube.py --local-cache    # Use local cached copy

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
    - **Episode numbers in titles (YouTube-specific)**
    - **Chapter timestamps in descriptions (YouTube-specific)**
"""

import os
import sys
import argparse
from dotenv import load_dotenv
from src.enrichment.enricher import FeedEnricher

# Load environment variables from .env
load_dotenv()


def main():
    """Enrich cd SPILL feed for YouTube."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Enrich cd SPILL feed for YouTube with Podcasting 2.0 tags and YouTube-specific modifications'
    )
    parser.add_argument(
        '--local-cache',
        action='store_true',
        help='Use local cached feed instead of fetching from network (for testing/development only)'
    )
    args = parser.parse_args()

    print("="*60)
    print("CD SPILL YOUTUBE FEED ENRICHER")
    print("="*60)

    # Determine source
    if args.local_cache:
        # For local testing, use the enriched feed that was generated
        cache_file = "docs/cdspill-enriched.xml"
        if not os.path.exists(cache_file):
            print(f"\n❌ Error: Enriched feed not found at {cache_file}")
            print("   Run enrich_cdspill.py first to generate the enriched feed")
            sys.exit(1)
        print(f"\n📁 Using local enriched feed: {cache_file}")
        source = cache_file
    else:
        # Fetch from already enriched feed (deployed on GitHub Pages)
        source = "https://mrmamen.github.io/podcast-feed-updater/cdspill-enriched.xml"

    # Initialize enricher
    enricher = FeedEnricher(source)

    # Fetch already enriched feed from GitHub Pages
    output_file = "docs/cdspill-youtube.xml"
    enricher.fetch_feed()

    print("\n📋 Source feed is already enriched with all Podcasting 2.0 tags")
    print("   Applying YouTube-specific modifications only...")

    # YouTube-specific modifications
    print("\n" + "="*60)
    print("YOUTUBE-SPECIFIC MODIFICATIONS")
    print("="*60)

    # Restore episode numbers to titles (YouTube displays these differently)
    enricher.restore_episode_numbers_to_titles()

    # Add chapter timestamps to descriptions (YouTube-compatible format)
    enricher.add_chapter_timestamps_to_description()

    # Remove chapter tags (YouTube doesn't support them, saves space)
    enricher.remove_chapter_tags()

    # Format podcast elements for better readability (call after all enrichment)
    enricher.format_podcast_elements()

    # Update feed metadata to reflect YouTube-specific location
    enricher.update_atom_link("https://mrmamen.github.io/podcast-feed-updater/cdspill-youtube.xml")
    enricher.update_generator("podcast-feed-updater v1.0 (YouTube variant)")
    enricher.update_lastBuildDate()

    # Create output directory
    os.makedirs("docs", exist_ok=True)

    # Write enriched feed
    enricher.write_feed(output_file)

    print("\n" + "="*60)
    print("DONE!")
    print("="*60)
    print("\nYouTube feed: docs/cdspill-youtube.xml")
    print("\nBase feed includes all standard Podcasting 2.0 enrichments")
    print("\nYouTube-specific modifications applied:")
    print("  ✓ Episode numbers restored to titles (e.g., 'OutRun med Mats Lindh (#123)')")
    print("  ✓ Bonus episodes kept without numbers (e.g., 'Bonus: Retro Crew: Westwood')")
    print("  ✓ Chapter timestamps added to descriptions (e.g., '0:00 Intro')")
    print("  ✓ Chapter tags removed (YouTube doesn't use them, saves space)")
    print("\nSource: Already enriched feed from GitHub Pages")
    print("Next steps:")
    print("  1. Review docs/cdspill-youtube.xml")
    print("  2. Verify episode titles: grep '<title>' docs/cdspill-youtube.xml | head")
    print("  3. Verify timestamps: grep '0:00' docs/cdspill-youtube.xml | head")
    print("  4. Upload to YouTube when ready")
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
