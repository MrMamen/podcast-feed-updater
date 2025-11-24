#!/usr/bin/env python3
"""
Split Rad Crew main feed into three enriched feeds.
Uses lxml to preserve namespace prefixes (itunes:, podcast:, etc.)

Usage:
    uv run split_radcrew.py         # Normal run with smart caching
    uv run split_radcrew.py --force # Force regeneration

Smart caching:
    - Checks if source feed has changed before regenerating
    - Skips processing if episode count is unchanged
    - Use --force to override and regenerate anyway
"""

import os
import sys
from src.radcrew.splitter import FeedSplitter


def main():
    """Split and enrich Rad Crew feeds."""
    # Check command line flags
    force_regenerate = "--force" in sys.argv

    print("="*60)
    print("RAD CREW FEED SPLITTER & ENRICHER")
    if force_regenerate:
        print("Mode: FORCE REGENERATE (ignoring cache)")
    print("="*60)

    # Create output directory
    os.makedirs("docs", exist_ok=True)

    # Initialize splitter
    splitter = FeedSplitter("https://feed.radcrew.net/radcrew")

    # Output files
    output_files = [
        "docs/radcrew-neon.xml",
        "docs/radcrew-retro.xml",
        "docs/radcrew-classic.xml",
    ]

    # Check if any output is missing or if feed has changed (unless --force)
    if not force_regenerate:
        # Check if all outputs exist
        all_exist = all(os.path.exists(f) for f in output_files)

        if all_exist:
            # Check if source has new episodes
            if not splitter.check_if_changed(output_files[0]):
                print("\n✓ Feeds are up to date, skipping regeneration")
                print("  (Use --force to regenerate anyway)")
                return

    # Fetch feed if we haven't already
    if splitter.source_episode_count is None:
        splitter.fetch_feed()

    # Define patterns and target metadata feeds
    patterns = [
        ("neon", True),        # Match "neon" -> NEON feed
        ("retro crew", True),  # Match "retro crew" -> Retro Crew feed
        # Everything else goes to Classic feed
    ]

    metadata_urls = [
        "https://feed.radcrew.net/radcrewneon",           # NEON metadata
        "https://www.radcrew.net/category/retrocrew/feed", # Retro Crew metadata
        "https://www.radcrew.net/category/classic/feed",   # Classic metadata
    ]

    # Split and merge
    print("\n" + "="*60)
    print("SPLITTING AND MERGING...")
    print("="*60)

    splitter.split_by_patterns(patterns, metadata_urls, output_files)

    # Save pubDate for next run
    splitter.save_latest_pubdate(output_files[0])

    print("\n" + "="*60)
    print("DONE!")
    print("="*60)
    print("\nGenerated feeds:")
    print(f"  1. docs/radcrew-neon.xml    (NEON episodes)")
    print(f"  2. docs/radcrew-retro.xml   (Retro Crew episodes)")
    print(f"  3. docs/radcrew-classic.xml (Classic Rad Crew episodes)")
    print("\nNext steps:")
    print("  1. Check the generated files")
    print("  2. Upload docs/ folder to Netlify")
    print("  3. Feeds will be at:")
    print("     - https://radcrew.netlify.app/radcrew-neon.xml")
    print("     - https://radcrew.netlify.app/radcrew-retro.xml")
    print("     - https://radcrew.netlify.app/radcrew-classic.xml")
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
