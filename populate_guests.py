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
import json
import re
import requests
from dotenv import load_dotenv
import os

load_dotenv()


def fetch_feed():
    """Fetch the cd SPILL feed."""
    print("📡 Fetching cd SPILL feed...")
    response = requests.get("https://feed.podbean.com/cdspill/feed.xml")
    response.raise_for_status()
    return response.text


def extract_guests_from_feed(feed_xml):
    """Extract all unique guest names from episode titles."""
    from lxml import etree

    root = etree.fromstring(feed_xml.encode('utf-8'))
    items = root.findall('.//item')

    all_guests = set()
    pattern = r'med (.+?)(?:\s*\(|$)'

    for item in items:
        title_elem = item.find('title')
        if title_elem is None or not title_elem.text:
            continue

        title = title_elem.text

        # Try to extract guest name(s)
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            guest_names_raw = match.group(1).strip()

            # Remove episode number if present
            guest_names_raw = re.sub(r'\s*\(#?\d+\)$', '', guest_names_raw)

            # Split multiple guests
            if ' og ' in guest_names_raw.lower():
                guest_names = re.split(r'\s+og\s+', guest_names_raw, flags=re.IGNORECASE)
            else:
                guest_names = [guest_names_raw]

            for guest_name in guest_names:
                guest_name = guest_name.strip()
                if guest_name:
                    all_guests.add(guest_name)

    return sorted(all_guests)


def authenticate_podchaser():
    """Authenticate with Podchaser API."""
    api_key = os.getenv('PODCHASER_API_KEY')
    api_secret = os.getenv('PODCHASER_API_SECRET')

    if not api_key or not api_secret:
        print("⚠ Missing Podchaser credentials in .env file")
        print("  Will add guests without profile data")
        return None

    mutation = '''
    mutation {
        requestAccessToken(
            input: {
                grant_type: CLIENT_CREDENTIALS
                client_id: "%s"
                client_secret: "%s"
            }
        ) {
            access_token
        }
    }
    ''' % (api_key, api_secret)

    response = requests.post(
        'https://api.podchaser.com/graphql',
        json={'query': mutation}
    )

    token_data = response.json()
    if 'errors' in token_data or 'data' not in token_data:
        print(f"⚠ Failed to authenticate with Podchaser")
        return None

    return token_data['data']['requestAccessToken']['access_token']


def search_podchaser(guest_name, access_token):
    """Search for a guest on Podchaser."""
    if not access_token:
        return None

    query = '''
    query {
      creators(searchTerm: "%s", first: 5) {
        data {
          name
          imageUrl
          url
        }
      }
    }
    ''' % guest_name

    try:
        response = requests.post(
            'https://api.podchaser.com/graphql',
            json={'query': query},
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {access_token}'
            },
            timeout=10
        )

        result = response.json()

        if 'errors' in result:
            return None

        creators = result.get('data', {}).get('creators', {}).get('data', [])

        # Return best match (first result with matching name)
        for creator in creators:
            # Exact match or very close match
            if creator['name'].lower() == guest_name.lower():
                return {
                    'name': creator['name'],
                    'img': creator.get('imageUrl'),
                    'href': creator.get('url')
                }

        # If no exact match, return first result if available
        if creators:
            return {
                'name': creators[0]['name'],
                'img': creators[0].get('imageUrl'),
                'href': creators[0].get('url')
            }

        return None

    except Exception as e:
        print(f"  ⚠ Error searching for {guest_name}: {e}")
        return None


def main():
    print("="*60)
    print("POPULATE KNOWN GUESTS")
    print("="*60)

    # Load existing known_guests
    known_guests_file = 'cdspill_known_guests.json'

    try:
        with open(known_guests_file, 'r', encoding='utf-8') as f:
            known_guests_data = json.load(f)
    except FileNotFoundError:
        print(f"⚠ File not found: {known_guests_file}")
        print(f"  Creating new file...")
        known_guests_data = {
            "_comment": "Known guests with Podchaser profile data and name aliases. Add new guests using: uv run python3 lookup_guest.py 'Guest Name'",
            "guests": {},
            "aliases": {}
        }

    existing_guests = set(known_guests_data['guests'].keys())
    existing_aliases = set(known_guests_data['aliases'].keys())
    all_known = existing_guests | existing_aliases

    print(f"\n📦 Currently in {known_guests_file}:")
    print(f"   {len(existing_guests)} guests")
    print(f"   {len(existing_aliases)} aliases")

    # Fetch feed and extract guests
    feed_xml = fetch_feed()
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
    access_token = authenticate_podchaser()

    if access_token:
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
        profile_data = search_podchaser(guest_name, access_token)

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

    # Sort guests and aliases alphabetically
    known_guests_data['guests'] = dict(sorted(known_guests_data['guests'].items()))
    known_guests_data['aliases'] = dict(sorted(known_guests_data['aliases'].items()))

    with open(known_guests_file, 'w', encoding='utf-8') as f:
        json.dump(known_guests_data, f, indent=2, ensure_ascii=False)
        f.write('\n')  # Add trailing newline

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
