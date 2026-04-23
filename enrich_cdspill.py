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
    Download the cache with: uv run python3 scripts/download_cdspill_cache.py

Person data:
    - Permanent staff: cdspill_permanent_staff.json (hosts and other permanent roles)
    - Known guests: cdspill_known_guests.json (profile images, URLs, name aliases)
    - Auto-detection: Guests detected from episode titles ("med [name]")
    - Lookup new guests: uv run python3 scripts/guests/lookup_guest.py "Guest Name"

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
import argparse
from dotenv import load_dotenv
from src.common.feed_loader import resolve_feed_source
from src.common.guest_config import KNOWN_GUESTS_PATH, load_known_guests_data
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

    # Determine source (exits if --local-cache set but cache missing)
    source = resolve_feed_source(use_cache=args.local_cache)
    if args.local_cache:
        print(f"\n📁 Using local cache: {source}")

    # Initialize enricher
    enricher = FeedEnricher(source)

    # Fetch feed
    output_file = "output/cdspill-enriched.xml"
    enricher.fetch_feed()

    # Validate that source feed doesn't already have Podcasting 2.0 tags
    # This will fail loudly if Podbean adds support for these tags
    enricher.validate_no_conflicts()

    # Remove episode numbers from titles
    enricher.remove_episode_numbers_from_titles()

    # Load permanent staff (hosts and other permanent roles)
    import json

    permanent_staff_file = "config/cdspill_permanent_staff.json"
    known_guests_file = str(KNOWN_GUESTS_PATH)

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
    if not KNOWN_GUESTS_PATH.exists():
        print(f"⚠ File not found: {known_guests_file}")
        print(f"  Guests will not have profile images")
        print(f"  Use 'uv run python3 scripts/guests/lookup_guest.py <name>' to add guest data")
    else:
        try:
            known_guests_data = load_known_guests_data()
            guests = known_guests_data.get('guests', {})
            aliases = known_guests_data.get('aliases', {})

            # Add guests with their profile data
            for name, data in guests.items():
                known_guests[name] = data

            # Add aliases (flattened into the same dict for the enricher)
            for alias, real_name in aliases.items():
                known_guests[alias] = {"alias": real_name}

            guests_with_images = sum(1 for g in guests.values() if g.get('img'))
            print(f"✓ Loaded {len(guests)} guests ({guests_with_images} with images) and {len(aliases)} aliases")
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
        dtstart="2020-03-09T00:00:00Z",
        rrule="FREQ=WEEKLY;INTERVAL=2"
    )

    # Add podroll (recommended podcasts)
    recommended_podcasts = [
        {
            "title": "Spæll",
            "url": "https://feed.podbean.com/spaell/feed.xml",
            "feedGuid": "ea5e71e4-fb02-51f7-936d-5acdb482be40"
        },
        {
            "title": "Retro Crew",
            "url": "https://radcrew.netlify.app/radcrew-retro.xml",
            "feedGuid": "a1324b88-c003-56a1-9de2-9160e28f2094"
        },
        {
            "title": "Retropodden",
            "url": "https://feeds.soundcloud.com/users/soundcloud:users:622595196/sounds.rss",
            "feedGuid": "7b33030d-fae9-54e1-a5fb-73da19ff901e"
        },
        {
            "title": "The Upper Memory Block",
            "url": "https://rss.libsyn.com/shows/327911/destinations/2668616.xml",
            "feedGuid": "56989d48-fc1a-5f62-8451-25f71b234b97"
        }
    ]
    enricher.add_podroll(recommended_podcasts)

    # Add social media interactions
    # Bluesky (AT Protocol)
    enricher.add_social_interact(
        protocol="disabled",
        uri="https://bsky.app/profile/cdspill.bsky.social",
        account_id="@cdspill.bsky.social",
        account_url="https://bsky.app/profile/cdspill.bsky.social",
        priority=8
    )

    # Twitter/X
    enricher.add_social_interact(
        protocol="disabled",
        uri="https://x.com/cd_SPILL",
        account_id="@cd_SPILL",
        account_url="https://x.com/cd_SPILL",
        priority=10
    )

    # Facebook (using disabled protocol per spec)
    enricher.add_social_interact(
        protocol="disabled",
        uri="https://www.facebook.com/cdSPILL",
        account_url="https://www.facebook.com/cdSPILL",
        priority=9
    )

    # Drop redundant description-like fields. Empirical testing showed no
    # client relies exclusively on itunes:summary or content:encoded — all
    # tested clients either use <description> or fall back to it.
    enricher.remove_itunes_summary()
    enricher.remove_content_encoded()

    # Add episode article link and social footer to descriptions
    enricher.add_description_footer(
        episode_article_domain="spillhistorie.no",
        episode_article_prefix="Spillhistorie har skrevet",
        episode_article_text="en artikkel om episoden",
        funding={
            "name": "Patreon",
            "url": "https://www.patreon.com/cdSPILL",
            "text": "Støtt oss gjerne på",
        },
        social_links=[
            {"name": "Bluesky", "url": "https://bsky.app/profile/cdspill.bsky.social"},
            {"name": "X", "url": "https://x.com/cd_SPILL"},
            {"name": "Facebook", "url": "https://www.facebook.com/cdSPILL"},
            {"name": "Podchaser", "url": "https://www.podchaser.com/cdSPILL"},
        ],
    )

    # Add OP3 analytics prefix for privacy-respecting download tracking
    enricher.add_op3_prefix()

    # Add language attribute to podcast:transcript tags (required by Apple Podcasts)
    enricher.add_language_to_transcripts(
        default_language="no",
        overrides={
            "0c247448-5242-370f-a0ba-775ad8c94ca4": "en",  # Martin Alper interview
        },
    )

    # Host chapter JSON files and rewrite podcast:chapters URLs to self-hosted.
    # psc:chapters is NOT added here — it's Spotify-specific and added by
    # enrich_cdspill_spotify.py so the main feed stays clean and Spotify can
    # be re-run independently of this script.
    enricher.convert_json_chapters_to_psc(include_psc_tags=False)

    # Format podcast elements for better readability (call after all enrichment)
    enricher.format_podcast_elements()

    # Update feed metadata to reflect actual published location
    enricher.update_atom_link("https://mrmamen.github.io/podcast-feed-updater/cdspill-enriched.xml")
    enricher.update_generator("podcast-feed-updater v1.0 (enriched from Podbean)")
    enricher.update_lastBuildDate()

    # Create output directory
    os.makedirs("docs", exist_ok=True)

    # Write enriched feed
    enricher.write_feed(output_file)

    print("\n" + "="*60)
    print("DONE!")
    print("="*60)
    print("\nEnriched feed: output/cdspill-enriched.xml")
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
    print("  ✓ Self-hosted chapter JSON files (podcast:chapters URLs rewritten)")
    print("\nPerson data files:")
    print(f"  📋 Permanent staff: {permanent_staff_file}")
    print(f"  📦 Known guests: {known_guests_file}")
    if os.path.exists(known_guests_file) and known_guests_data:
        guests = known_guests_data.get('guests', {})
        aliases = known_guests_data.get('aliases', {})
        guests_with_img = sum(1 for g in guests.values() if g.get('img'))
        print(f"     → {len(guests)} guests ({guests_with_img} with images), {len(aliases)} aliases")
    print("\nNext steps:")
    print("  1. Review output/cdspill-enriched.xml")
    print("  2. Add new guests: uv run python3 scripts/guests/lookup_guest.py 'Guest Name'")
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
