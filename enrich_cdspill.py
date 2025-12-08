#!/usr/bin/env python3
"""
Enrich cd SPILL feed with Podcasting 2.0 tags.
Adds host/guest information, funding links, and rich metadata.

Usage:
    uv run enrich_cdspill.py                  # Fetch from online source
    uv run enrich_cdspill.py --local-cache    # Use local cached copy

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
from dotenv import load_dotenv
from src.enrichment.enricher import FeedEnricher

# Load environment variables from .env
load_dotenv()


def main():
    """Enrich cd SPILL feed."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Enrich cd SPILL feed with Podcasting 2.0 tags'
    )
    parser.add_argument(
        '--local-cache',
        action='store_true',
        help='Use local cached feed instead of fetching from network (for testing/development only)'
    )
    args = parser.parse_args()

    print("="*60)
    print("CD SPILL FEED ENRICHER")
    print("="*60)

    # Determine source
    if args.local_cache:
        cache_file = ".cache/cdspill-original.xml"
        if not os.path.exists(cache_file):
            print(f"\n❌ Error: Local cache not found at {cache_file}")
            print("   Download the cache first with: uv run python3 download_cdspill_cache.py")
            sys.exit(1)
        print(f"\n📁 Using local cache: {cache_file}")
        source = cache_file
    else:
        source = "https://feed.podbean.com/cdspill/feed.xml"

    # Initialize enricher
    enricher = FeedEnricher(source)

    # Fetch feed
    output_file = "docs/cdspill-enriched.xml"
    enricher.fetch_feed()

    # Validate that source feed doesn't already have Podcasting 2.0 tags
    # This will fail loudly if Podbean adds support for these tags
    enricher.validate_no_conflicts()

    # Remove episode numbers from titles
    enricher.remove_episode_numbers_from_titles()

    # Load permanent staff (hosts and other permanent roles)
    import json

    permanent_staff_file = "cdspill_permanent_staff.json"
    known_guests_file = "cdspill_known_guests.json"

    hosts = []
    known_guests_data = None

    # Load permanent staff config
    print(f"\n📋 Loading permanent staff from: {permanent_staff_file}")
    try:
        with open(permanent_staff_file, 'r', encoding='utf-8') as f:
            permanent_staff = json.load(f)

        # Get hosts from config (already includes img/href if defined)
        hosts = permanent_staff.get('hosts', [])
        print(f"✓ Loaded {len(hosts)} permanent host(s)")

        for host in hosts:
            img_status = "📷" if 'img' in host else "  "
            href_status = "🔗" if 'href' in host else "  "
            print(f"  {img_status}{href_status} {host['name']} ({host['role']})")

    except FileNotFoundError:
        print(f"⚠ Config file not found: {permanent_staff_file}")
        print(f"  Using empty host list")
    except Exception as e:
        print(f"⚠ Error loading config: {e}")

    enricher.add_channel_persons(hosts)

    # Add podcast GUID (unique identifier for the podcast)
    enricher.add_guid("a550e4b5-6615-5a5d-b1d5-a371c01552a2")

    # Add podcast:season and podcast:episode tags
    enricher.add_podcast_season_episode()

    # Auto-detect guests from episode titles
    # Episodes with "med Guest Name" will automatically get guest tags
    # Multiple guests separated by " og " are automatically split into separate tags

    # Load known guests data (images, URLs, aliases)
    known_guests = {}

    print(f"\n📦 Loading known guests from: {known_guests_file}")
    try:
        with open(known_guests_file, 'r', encoding='utf-8') as f:
            known_guests_data = json.load(f)

        guests = known_guests_data.get('guests', {})
        aliases = known_guests_data.get('aliases', {})

        # Add guests with their profile data
        for name, data in guests.items():
            known_guests[name] = data

        # Add aliases
        for alias, real_name in aliases.items():
            known_guests[alias] = {"alias": real_name}

        guests_with_images = sum(1 for g in guests.values() if g.get('img'))
        print(f"✓ Loaded {len(guests)} guests ({guests_with_images} with images) and {len(aliases)} aliases")

    except FileNotFoundError:
        print(f"⚠ File not found: {known_guests_file}")
        print(f"  Guests will not have profile images")
        print(f"  Use 'uv run python3 lookup_guest.py <name>' to add guest data")
    except Exception as e:
        print(f"⚠ Error loading known guests: {e}")

    enricher.auto_detect_guests_from_titles(
        pattern=r'med (.+?)(?:\s*\(|$)',  # Matches "med Guest Name (optional #123)"
        known_guests=known_guests
    )

    # Add funding (Patreon)
    enricher.add_funding(
        url="https://www.patreon.com/cdSPILL",
        message="Støtt cd SPILL på Patreon"
    )

    # Add medium type
    enricher.add_medium("podcast")

    # Add update frequency (biweekly: every other week, started March 2020)
    # FREQ=WEEKLY;INTERVAL=2 means every 2 weeks
    # Change to complete=True if the podcast is finished
    enricher.add_update_frequency(
        complete=False,
        frequency=2,
        dtstart="2020-03-09",
        rrule="FREQ=WEEKLY;INTERVAL=2"
    )

    # Add podroll (recommended podcasts)
    recommended_podcasts = [
        {
            "feedTitle": "Spæll",
            "url": "https://feed.podbean.com/spaell/feed.xml",
            "feedGuid": "ea5e71e4-fb02-51f7-936d-5acdb482be40"
        },
        {
            "feedTitle": "Retro Crew",
            "url": "https://radcrew.netlify.app/radcrew-retro.xml",
            "feedGuid": "a1324b88-c003-56a1-9de2-9160e28f2094"
        },
        {
            "feedTitle": "Retropodden",
            "url": "https://feeds.soundcloud.com/users/soundcloud:users:622595196/sounds.rss",
            "feedGuid": "7b33030d-fae9-54e1-a5fb-73da19ff901e"
        },
        {
            "feedTitle": "The Upper Memory Block",
            "url": "https://rss.libsyn.com/shows/327911/destinations/2668616.xml",
            "feedGuid": "56989d48-fc1a-5f62-8451-25f71b234b97"
        }
    ]
    enricher.add_podroll(recommended_podcasts)

    # Add social media interactions
    # Bluesky (ActivityPub)
    enricher.add_social_interact(
        protocol="activitypub",
        uri="https://bsky.app/profile/cdspill.bsky.social",
        account_id="@cdspill.bsky.social"
    )

    # Twitter/X
    enricher.add_social_interact(
        protocol="twitter",
        uri="https://x.com/cd_SPILL",
        account_id="@cd_SPILL"
    )

    # Facebook (using disabled protocol per spec)
    enricher.add_social_interact(
        protocol="disabled",
        uri="https://www.facebook.com/cdSPILL"
    )

    # Add OP3 analytics prefix for privacy-respecting download tracking
    enricher.add_op3_prefix()

    # Convert JSON chapters to Podlove Simple Chapters format
    enricher.convert_json_chapters_to_psc()

    # Format podcast elements for better readability (call after all enrichment)
    enricher.format_podcast_elements()

    # Create output directory
    os.makedirs("docs", exist_ok=True)

    # Write enriched feed
    enricher.write_feed(output_file)

    print("\n" + "="*60)
    print("DONE!")
    print("="*60)
    print("\nEnriched feed: docs/cdspill-enriched.xml")
    print("\nWhat was added:")
    print(f"  ✓ {len(hosts)} permanent host(s) with profile images and URLs")
    print("  ✓ Podcast GUID: Unique identifier for feed portability")
    print("  ✓ Season/episode tags with season names (e.g., 'Vår 2020')")
    print("  ✓ Auto-detected guests from episode titles (with profile data)")
    print("  ✓ Patreon funding link")
    print("  ✓ Medium type: podcast")
    print("  ✓ Update frequency: biweekly schedule")
    print("  ✓ Podroll: 4 recommended podcasts")
    print("  ✓ Social interactions: Bluesky, Twitter/X, Facebook")
    print("  ✓ OP3 analytics: Privacy-respecting download tracking")
    print("  ✓ Podlove Simple Chapters: Inline chapter markers")
    print("\nPerson data files:")
    print(f"  📋 Permanent staff: {permanent_staff_file}")
    print(f"  📦 Known guests: {known_guests_file}")
    if os.path.exists(known_guests_file) and known_guests_data:
        guests = known_guests_data.get('guests', {})
        aliases = known_guests_data.get('aliases', {})
        guests_with_img = sum(1 for g in guests.values() if g.get('img'))
        print(f"     → {len(guests)} guests ({guests_with_img} with images), {len(aliases)} aliases")
    print("\nNext steps:")
    print("  1. Review docs/cdspill-enriched.xml")
    print("  2. Add new guests: uv run python3 lookup_guest.py 'Guest Name'")
    print("  3. Upload to hosting when ready")
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
