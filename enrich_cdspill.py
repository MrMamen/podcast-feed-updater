#!/usr/bin/env python3
"""
Enrich cd SPILL feed with Podcasting 2.0 tags.
Adds host/guest information and funding links.

Usage:
    uv run enrich_cdspill.py              # Without Podchaser (default, recommended)
    uv run enrich_cdspill.py --podchaser  # With Podchaser API (when API is available)
    uv run enrich_cdspill.py --force      # Force regeneration even if no changes detected

The script adds:
    - 2 default hosts (Sigve & Hans-Henrik)
    - Guest information for episodes matching patterns
    - Patreon funding link
    - Bluesky social interaction

Smart caching:
    - Checks latest episode's pubDate AND link before regenerating
    - Detects new episodes (pubDate change) AND updated episodes (link change)
    - Skips processing if no changes detected
    - Use --force to override and regenerate anyway
    - Perfect for automated GitHub Actions workflows
"""

import os
import sys
from dotenv import load_dotenv
from src.enrichment.enricher import FeedEnricher

# Load environment variables from .env
load_dotenv()


def main():
    """Enrich cd SPILL feed."""
    # Check command line flags
    use_podchaser = "--podchaser" in sys.argv
    force_regenerate = "--force" in sys.argv

    print("="*60)
    print("CD SPILL FEED ENRICHER")
    if use_podchaser:
        print("Mode: WITH Podchaser API")
    else:
        print("Mode: Manual data (use --podchaser flag to enable API)")
    if force_regenerate:
        print("Mode: FORCE REGENERATE (ignoring cache)")
    print("="*60)

    # Initialize enricher
    enricher = FeedEnricher("https://feed.podbean.com/cdspill/feed.xml")

    # Check if feed has changed (unless --force)
    output_file = "docs/cdspill-enriched.xml"
    if not force_regenerate:
        if not enricher.check_if_changed(output_file):
            print("\n✓ Feed is up to date, skipping regeneration")
            print("  (Use --force to regenerate anyway)")
            return

    # Fetch feed if we haven't already (check_if_changed might have done it)
    if enricher.source_latest_pubdate is None:
        enricher.fetch_feed()

    # Add beta suffix to title
    enricher.set_beta_title(" (Beta)")

    # Define hosts manually (always available as fallback)
    manual_hosts = [
        {
            "name": "Sigve Indregard",
            "role": "host",
            "href": "https://www.podchaser.com/creators/sigve-indregard-107ZbOzxDQ",
        },
        {
            "name": "Hans-Henrik Mamen",
            "role": "host",
            "href": "https://www.podchaser.com/creators/hans-henrik-mamen-107ZbOzNaP",
        },
    ]

    hosts = manual_hosts  # Default to manual data

    # Only try Podchaser if flag is set
    if use_podchaser:
        print("\n" + "="*60)
        print("FETCHING HOSTS FROM PODCHASER API")
        print("="*60)

        api_key = os.environ.get('PODCHASER_API_KEY')
        api_secret = os.environ.get('PODCHASER_API_SECRET')

        if not api_key or not api_secret:
            print("\n⚠ WARNING: Missing Podchaser credentials!")
            print("Required in .env file:")
            print("  PODCHASER_API_KEY=your_client_id")
            print("  PODCHASER_API_SECRET=your_client_secret")
            print("\nGet credentials at: https://www.podchaser.com/api")
            print("\nFalling back to manual host data...\n")
        else:
            try:
                from src.enrichment.podchaser_api import PodchaserAPI

                # Use Podchaser API
                api = PodchaserAPI(api_key, api_secret)

                if not api.access_token:
                    print("⚠ Failed to authenticate with Podchaser")
                    print("Falling back to manual host data...\n")
                else:
                    podchaser_hosts = api.enrich_feed_with_creators("cd SPILL")

                    if podchaser_hosts:
                        hosts = podchaser_hosts
                        print(f"✓ Fetched {len(hosts)} hosts from Podchaser API")
                        for host in hosts:
                            print(f"  - {host['name']} ({host['role']})")
                    else:
                        print("⚠ Could not fetch from Podchaser, using manual data")
            except Exception as e:
                print(f"⚠ Error with Podchaser API: {e}")
                print("Falling back to manual host data...\n")
    else:
        print(f"\nUsing manual host data ({len(manual_hosts)} hosts)")

    enricher.add_channel_persons(hosts)

    # Add podcast GUID (unique identifier for the podcast)
    enricher.add_guid("a550e4b5-6615-5a5d-b1d5-a371c01552a2")

    # Add podcast:season and podcast:episode tags
    enricher.add_podcast_season_episode()

    # Auto-detect guests from episode titles
    # Episodes with "med Guest Name" will automatically get guest tags
    # Multiple guests separated by " og " are automatically split into separate tags
    # Optional: Add known guest info for profiles/images
    # Use 'alias' key to normalize name variations (e.g., "Aksel Bjerke" → "Aksel M. Bjerke")
    known_guests = {
        "Anette Jøsendal": {
            "href": "https://www.podchaser.com/creators/anette-josendal-107ZbPSK9m"
        },
        "Roar Granevang": {
            "href": "https://www.podchaser.com/creators/roar-granevang-107ZbQKYBB"
        },
        "Jostein Hakestad": {
            # Add href when available
        },
        "Kent William Innholt": {
            # Add href when available
        },
        "Trond Sneås Skauge": {
            # Add href when available
        },
        "Øystein Henriksen": {
            # Add href when available
        },
        "Thorbjørn Hope Andersen": {
            # Add href when available
        },
        "Joachim Froholt": {
            # Add href when available
        },
        "David Skaufjord": {
            # Add href when available
        },
        "Terje Høiback": {
            # Add href when available
        },
        # Name normalizations (aliases)
        "Aksel Bjerke": {
            "alias": "Aksel M. Bjerke"
            # Will use the same href as "Aksel M. Bjerke" if defined
        },
        "Aksel M. Bjerke": {
            # Add href when available
        },
        "Aleksander": {
            "alias": "Aleksander Hakestad"
            # Normalize to full name for consistency
        },
        "Aleksander Hakestad": {
            # Add href when available
        }
        # Add more known guests here with their profile URLs
    }

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

    # Create output directory
    os.makedirs("docs", exist_ok=True)

    # Write enriched feed
    enricher.write_feed(output_file)

    # Save cache for next run
    enricher.save_cache(output_file)

    print("\n" + "="*60)
    print("DONE!")
    print("="*60)
    print("\nEnriched feed: docs/cdspill-enriched.xml")
    print("\nWhat was added:")
    print("  ✓ Beta title suffix for testing")
    print("  ✓ 2 default hosts (Sigve & Hans-Henrik)")
    print("  ✓ Podcast GUID: Unique identifier for feed portability")
    print("  ✓ Season/episode tags with season names (e.g., 'Vår 2020')")
    print("  ✓ Auto-detected guests from episode titles")
    print("  ✓ Patreon funding link")
    print("  ✓ Medium type: podcast")
    print("  ✓ Update frequency: biweekly schedule")
    print("  ✓ Podroll: 4 recommended podcasts")
    print("  ✓ Social interactions: Bluesky, Twitter/X, Facebook")
    print("  ✓ OP3 analytics: Privacy-respecting download tracking")
    print("  ✓ Podlove Simple Chapters: Inline chapter markers")
    print("\nNext steps:")
    print("  1. Review docs/cdspill-enriched.xml")
    print("  2. Add more guest mappings to episode_guests dict")
    print("  3. Add profile images for hosts/guests")
    print("  4. Upload to hosting when ready")
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
