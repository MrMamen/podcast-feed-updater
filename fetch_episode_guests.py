#!/usr/bin/env python3
"""
Fetch all guests for a specific episode from Podchaser.
Generates extra_episodes JSON that can be added to cdspill_known_guests.json.

Usage:
    uv run python3 fetch_episode_guests.py "Episode Title"
    uv run python3 fetch_episode_guests.py "cdspill.podbean.com/guid"
    uv run python3 fetch_episode_guests.py "#106"
"""

import sys
import json
import requests
from dotenv import load_dotenv
import os
from lxml import etree

load_dotenv()


def authenticate_podchaser():
    """Authenticate with Podchaser API."""
    api_key = os.getenv('PODCHASER_API_KEY')
    api_secret = os.getenv('PODCHASER_API_SECRET')

    if not api_key or not api_secret:
        print("❌ Error: PODCHASER_API_KEY and PODCHASER_API_SECRET must be set in .env")
        sys.exit(1)

    response = requests.post(
        'https://api.podchaser.com/oauth/token',
        json={
            'grant_type': 'client_credentials',
            'client_id': api_key,
            'client_secret': api_secret
        }
    )

    if response.status_code != 200:
        print(f"❌ Authentication failed: {response.status_code}")
        print(response.text)
        sys.exit(1)

    return response.json()['access_token']


def fetch_feed():
    """Fetch the cd SPILL feed."""
    response = requests.get("https://feed.podbean.com/cdspill/feed.xml")
    response.raise_for_status()
    return response.text


def find_episode_in_feed(feed_xml, search_term):
    """
    Find episode in feed by title, GUID, or episode number.
    Returns (guid, title, url) tuple or None.
    """
    root = etree.fromstring(feed_xml.encode('utf-8'))
    items = root.findall('.//item')

    # Check if search term is an episode number (e.g., "#106" or "106")
    episode_number = None
    if search_term.startswith('#'):
        episode_number = search_term[1:]
    elif search_term.isdigit():
        episode_number = search_term

    for item in items:
        # Get episode details
        title_elem = item.find('title')
        guid_elem = item.find('guid')
        link_elem = item.find('link')
        episode_elem = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}episode')

        title = title_elem.text if title_elem is not None else ''
        guid = guid_elem.text if guid_elem is not None else ''
        url = link_elem.text if link_elem is not None else ''
        episode_num = episode_elem.text if episode_elem is not None else ''

        # Match by episode number
        if episode_number and episode_num == episode_number:
            return guid, title, url

        # Match by GUID
        if search_term in guid:
            return guid, title, url

        # Match by title (case insensitive, partial match)
        if search_term.lower() in title.lower():
            return guid, title, url

    return None, None, None


def search_episode_on_podchaser(episode_title, access_token):
    """Search for episode on Podchaser by title."""
    # Remove episode number from title for better search
    import re
    clean_title = re.sub(r'\s*\(#?\d+\)$', '', episode_title)

    query = '''
    query {
      episodes(searchTerm: "%s", first: 5) {
        data {
          id
          title
          url
        }
      }
    }
    ''' % clean_title

    response = requests.post(
        'https://api.podchaser.com/graphql',
        json={'query': query},
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {access_token}'
        }
    )

    print(f"Query cost: {response.headers.get('X-Podchaser-Query-Cost')}")
    print(f"Points remaining: {response.headers.get('X-Podchaser-Points-Remaining')}")
    print()

    result = response.json()

    if 'errors' in result:
        print(f"❌ Error: {result['errors']}")
        return None

    episodes = result.get('data', {}).get('episodes', {}).get('data', [])

    # Try to find exact match
    for episode in episodes:
        if episode['title'].lower() == clean_title.lower():
            return episode

    # If no exact match, return first result
    return episodes[0] if episodes else None


def fetch_episode_credits(episode_id, access_token):
    """Fetch credits for a specific episode."""
    query = '''
    query {
      episode(identifier: { type: PODCHASER, id: "%s" }) {
        title
        credits {
          data {
            role {
              title
            }
            creator {
              name
              imageUrl
              url
            }
          }
        }
      }
    }
    ''' % episode_id

    response = requests.post(
        'https://api.podchaser.com/graphql',
        json={'query': query},
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {access_token}'
        }
    )

    query_cost = response.headers.get('X-Podchaser-Query-Cost')
    points_remaining = response.headers.get('X-Podchaser-Points-Remaining')

    print(f"Query cost: {query_cost}")
    print(f"Points remaining: {points_remaining}")
    print()

    if response.status_code != 200:
        print(f"❌ HTTP Error {response.status_code}: {response.text}")
        return []

    result = response.json()

    if 'errors' in result:
        print(f"❌ GraphQL Error: {result['errors']}")
        return []

    if not result.get('data'):
        print(f"❌ No data in response. Full response: {result}")
        return []

    episode = result.get('data', {}).get('episode', {})
    if not episode:
        return []

    return episode.get('credits', {}).get('data', [])


def load_known_guests():
    """Load existing known guests."""
    try:
        with open('cdspill_known_guests.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('guests', {}), data.get('aliases', {})
    except FileNotFoundError:
        return {}, {}


def main():
    if len(sys.argv) < 2:
        print("Usage: uv run python3 fetch_episode_guests.py \"Episode Title or GUID or #106\"")
        sys.exit(1)

    search_term = sys.argv[1]

    print("="*60)
    print("FETCH EPISODE GUESTS FROM PODCHASER")
    print("="*60)
    print()

    # Find episode in feed
    print(f"🔍 Searching for episode: {search_term}")
    feed_xml = fetch_feed()
    guid, title, url = find_episode_in_feed(feed_xml, search_term)

    if not guid:
        print(f"❌ Episode not found in feed")
        sys.exit(1)

    print(f"✓ Found episode:")
    print(f"  Title: {title}")
    print(f"  GUID: {guid}")
    print(f"  URL: {url}")
    print()

    # Authenticate with Podchaser
    print("🔑 Authenticating with Podchaser...")
    access_token = authenticate_podchaser()
    print("✓ Authenticated")
    print()

    # Search for episode on Podchaser
    print(f"📡 Searching for episode on Podchaser...")
    episode_data = search_episode_on_podchaser(title, access_token)

    if not episode_data:
        print("❌ Episode not found on Podchaser")
        sys.exit(1)

    print(f"✓ Found: {episode_data['title']}")
    print(f"  Podchaser ID: {episode_data['id']}")
    print(f"  URL: {episode_data.get('url', 'N/A')}")
    print()

    # Fetch credits for this episode
    print(f"📡 Fetching episode credits...")
    credits = fetch_episode_credits(episode_data['id'], access_token)

    # Extract guests from credits
    guests = []
    for credit in credits:
        role_title = credit.get('role', {}).get('title', '').lower()
        # Include guests and anyone who is not a host/producer
        if 'guest' in role_title or role_title in ['', 'creator', 'participant']:
            creator = credit.get('creator', {})
            if creator:
                guests.append(creator)

    if not guests:
        print("⚠️  No guests found for this episode on Podchaser")
        sys.exit(0)

    print(f"✓ Found {len(guests)} guest(s):")
    print()

    # Load existing known guests
    known_guests, aliases = load_known_guests()

    # Process guests
    guests_to_add = []
    already_in_feed = []

    for guest in guests:
        name = guest['name']
        print(f"  • {name}")

        # Check if guest is in known_guests
        if name in known_guests:
            print(f"    ✓ Already in cdspill_known_guests.json")
            already_in_feed.append(name)
        else:
            print(f"    ⚠️  Not in cdspill_known_guests.json")
            guests_to_add.append({
                'name': name,
                'img': guest.get('imageUrl'),
                'href': guest.get('url')
            })

    print()
    print("="*60)
    print("EXTRA_EPISODES JSON")
    print("="*60)
    print()

    if already_in_feed:
        print("✅ Guests already in known_guests.json:")
        print()
        for name in already_in_feed:
            guest_data = known_guests[name]

            # Check if this guest already has this episode in extra_episodes
            extra_eps = guest_data.get('extra_episodes', [])
            has_episode = any(ep['guid'] == guid for ep in extra_eps)

            if has_episode:
                print(f'  // "{name}" already has this episode in extra_episodes')
            else:
                print(f'  "{name}": {{')
                if 'img' in guest_data:
                    print(f'    "img": "{guest_data["img"]}",')
                if 'href' in guest_data:
                    print(f'    "href": "{guest_data["href"]}",')
                print(f'    "extra_episodes": [')
                print(f'      {{')
                print(f'        "guid": "{guid}",')
                print(f'        "note": "{title}"')
                print(f'      }}')
                print(f'    ]')
                print(f'  }},')
        print()

    if guests_to_add:
        print("⚠️  Guests NOT in known_guests.json (add these first):")
        print()
        for guest in guests_to_add:
            print(f'  // Add {guest["name"]} first with:')
            print(f'  // uv run python3 lookup_guest.py "{guest["name"]}"')
            print(f'  // or')
            print(f'  // uv run python3 add_guest_from_url.py "{guest["href"]}"')
        print()

    print()
    print("💡 Copy the JSON above and add to cdspill_known_guests.json")
    print("   (merge with existing extra_episodes arrays if present)")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
