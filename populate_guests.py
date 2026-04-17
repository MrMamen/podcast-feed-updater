#!/usr/bin/env python3
"""
Automatically populate cdspill_known_guests.json with all guests found in episode titles.

For each new guest:
1. Search Podchaser API for profile data
2. If found, add with img and href
3. If not found, add anyway but without img/href
4. Guests already in the file are skipped (no re-lookup)

Usage:
    uv run python3 populate_guests.py
"""

import sys

from dotenv import load_dotenv
from lxml import etree

from src.common.feed_loader import load_feed
from src.common.guest_config import (
    KNOWN_GUESTS_PATH,
    load_known_guests_data,
    save_known_guests,
)
from src.common.podcast_utils import extract_guests_from_title
from src.enrichment.podchaser_api import PodchaserAPI, from_env

load_dotenv()


def extract_guests_from_feed(feed_xml):
    """Extract all unique guest names from episode titles."""
    root = etree.fromstring(feed_xml.encode('utf-8'))
    all_guests = set()

    for item in root.findall('.//item'):
        title_elem = item.find('title')
        if title_elem is None or not title_elem.text:
            continue
        for guest_name in extract_guests_from_title(title_elem.text):
            all_guests.add(guest_name)

    return sorted(all_guests)


def search_podchaser(guest_name, client: PodchaserAPI | None):
    """Search for a guest on Podchaser. Returns best-match dict or None."""
    if client is None:
        return None

    try:
        creators = client.search_creator(guest_name, first=5)
    except Exception as e:
        print(f"  ⚠ Error searching for {guest_name}: {e}")
        return None

    for creator in creators:
        if creator.get('name', '').lower() == guest_name.lower():
            return {
                'name': creator['name'],
                'img': creator.get('imageUrl'),
                'href': creator.get('url'),
            }

    if creators:
        best = creators[0]
        return {
            'name': best['name'],
            'img': best.get('imageUrl'),
            'href': best.get('url'),
        }

    return None


def main():
    print("="*60)
    print("POPULATE KNOWN GUESTS")
    print("="*60)

    # Load existing known_guests
    known_guests_file = str(KNOWN_GUESTS_PATH)
    if not KNOWN_GUESTS_PATH.exists():
        print(f"⚠ File not found: {known_guests_file}")
        print(f"  Creating new file...")
    known_guests_data = load_known_guests_data()

    existing_guests = set(known_guests_data['guests'].keys())
    existing_aliases = set(known_guests_data['aliases'].keys())
    all_known = existing_guests | existing_aliases

    print(f"\n📦 Currently in {known_guests_file}:")
    print(f"   {len(existing_guests)} guests")
    print(f"   {len(existing_aliases)} aliases")

    # Fetch feed and extract guests
    feed_xml = load_feed(use_cache=False)
    all_guests = extract_guests_from_feed(feed_xml)

    print(f"\n🔍 Found {len(all_guests)} unique guests in episode titles")

    # Find new guests
    new_guests = [g for g in all_guests if g not in all_known]

    if not new_guests:
        print("\n✓ All guests already in known_guests.json - nothing to do!")
        return

    print(f"\n🆕 Found {len(new_guests)} new guests to add:")
    for guest in new_guests:
        print(f"   - {guest}")

    # Authenticate with Podchaser
    print(f"\n🔑 Authenticating with Podchaser...")
    client = from_env(required=False)

    if client is not None:
        print("✓ Authenticated successfully")
    else:
        print("⚠ No Podchaser access - will add guests without profile data")

    # Process each new guest
    print(f"\n{'='*60}")
    print("PROCESSING NEW GUESTS")
    print(f"{'='*60}\n")

    added_count = 0
    with_profile_count = 0
    without_profile_count = 0

    for i, guest_name in enumerate(new_guests, 1):
        print(f"[{i}/{len(new_guests)}] {guest_name}")

        # Search Podchaser
        profile_data = search_podchaser(guest_name, client)

        if profile_data:
            guest_data = {}
            if profile_data.get('img'):
                guest_data['img'] = profile_data['img']
            if profile_data.get('href'):
                guest_data['href'] = profile_data['href']

            if guest_data:
                print(f"  ✓ Found profile data")
                if 'img' in guest_data:
                    print(f"    📷 Image: ✓")
                if 'href' in guest_data:
                    print(f"    🔗 URL: ✓")
                with_profile_count += 1
            else:
                print(f"  ⚠ Found in Podchaser but no data available")
                guest_data = {}
                without_profile_count += 1

            known_guests_data['guests'][guest_name] = guest_data
        else:
            print(f"  ⚠ Not found in Podchaser")
            known_guests_data['guests'][guest_name] = {}
            without_profile_count += 1

        added_count += 1

    # Save updated file
    print(f"\n💾 Saving to {known_guests_file}...")
    save_known_guests(known_guests_data)

    print("\n" + "="*60)
    print("DONE!")
    print("="*60)
    print(f"\n✓ Added {added_count} new guests:")
    print(f"  📷 {with_profile_count} with profile data")
    print(f"  ⚠ {without_profile_count} without profile data")
    print(f"\n📊 Total in {known_guests_file}:")
    print(f"   {len(known_guests_data['guests'])} guests")
    print(f"   {len(known_guests_data['aliases'])} aliases")
    print(f"\n💡 Run 'uv run enrich_cdspill.py' to use the updated data")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
