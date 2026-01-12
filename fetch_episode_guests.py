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
    Returns (guid, title, url, episode_num) tuple or None.
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
            return guid, title, url, episode_num

        # Match by GUID
        if search_term in guid:
            return guid, title, url, episode_num

        # Match by title (case insensitive, partial match)
        if search_term.lower() in title.lower():
            return guid, title, url, episode_num

    return None, None, None, None


def search_episode_on_podchaser(episode_title, access_token):
    """Search for episode on Podchaser by title within cd SPILL podcast."""
    # Remove episode number from title for better search
    import re
    clean_title = re.sub(r'\s*\(#?\d+\)$', '', episode_title)

    # cd SPILL podcast ID on Podchaser
    CDSPILL_PODCAST_ID = "1540724"

    query = '''
    query {
      podcast(identifier: { type: PODCHASER, id: "%s" }) {
        title
        episodes(searchTerm: "%s", first: 5) {
          data {
            id
            title
            url
          }
        }
      }
    }
    ''' % (CDSPILL_PODCAST_ID, clean_title)

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

    podcast = result.get('data', {}).get('podcast', {})
    episodes = podcast.get('episodes', {}).get('data', [])

    # Try to find exact match
    for episode in episodes:
        if episode['title'].lower() == clean_title.lower():
            return episode

    # If no exact match, return first result
    return episodes[0] if episodes else None


def check_query_cost(query, access_token):
    """Check the cost of a query before executing it."""
    response = requests.post(
        'https://api.podchaser.com/graphql/cost',
        json={'query': query},
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {access_token}'
        }
    )

    if response.status_code == 200:
        data = response.json()
        return data.get('cost', 0)
    return None


def fetch_episode_credits(episode_id, access_token):
    """Fetch credits for a specific episode."""
    query = '''
    query {
      episode(identifier: { type: PODCHASER, id: "%s" }) {
        title
        credits(first: 100) {
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

    # Check cost first
    cost = check_query_cost(query, access_token)
    if cost:
        print(f"📊 Estimated query cost: {cost} points")

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
    guid, title, url, episode_num = find_episode_in_feed(feed_xml, search_term)

    if not guid:
        print(f"❌ Episode not found in feed")
        sys.exit(1)

    print(f"✓ Found episode:")
    print(f"  Title: {title}")
    if episode_num:
        print(f"  Episode: #{episode_num}")
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

    # Show all credits for reference
    print("📋 All episode credits from Podchaser:")
    production_roles = {'host', 'editor', 'audio editor', 'producer', 'executive producer',
                       'social media manager', 'theme music', 'songwriter', 'cover art'}

    guests = []
    other_people = []

    for credit in credits:
        creator = credit.get('creator', {})
        creator_name = creator.get('name', 'Unknown')
        role_title = credit.get('role', {}).get('title', '')
        role_title_lower = role_title.lower()

        print(f"  • {creator_name}: {role_title}")

        # Categorize the person
        if role_title_lower in production_roles:
            # Skip production roles
            continue
        elif 'guest' in role_title_lower:
            guests.append(creator)
        elif role_title_lower in ['consultant', 'contributor', 'participant']:
            # Potentially guests but not explicitly marked
            other_people.append((creator, role_title))

    print()

    if other_people:
        print(f"⚠️  Found {len(other_people)} person(s) with ambiguous roles:")
        for person, role in other_people:
            print(f"  • {person['name']}: {role}")
        print("  These are NOT automatically included. Add manually if they are guests.")
        print()

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
    guests_in_title = []

    for guest in guests:
        name = guest['name']
        print(f"  • {name}")

        # Resolve alias to canonical name
        canonical_name = aliases.get(name, name)

        # Check if guest is already in the episode title (check both name and canonical name)
        # If so, they will be auto-detected and don't need extra_episodes
        if name in title or canonical_name in title:
            print(f"    ℹ️  Already in episode title (will be auto-detected)")
            guests_in_title.append(canonical_name)
            continue

        # Check if guest is in known_guests (either directly or via alias)
        if canonical_name in known_guests:
            if name != canonical_name:
                print(f"    ✓ Found via alias '{name}' → '{canonical_name}'")
            else:
                print(f"    ✓ Already in cdspill_known_guests.json")
            already_in_feed.append(canonical_name)
        else:
            print(f"    ⚠️  Not in cdspill_known_guests.json")
            guests_to_add.append({
                'name': name,
                'img': guest.get('imageUrl'),
                'href': guest.get('url')
            })

    print()
    print("="*60)
    print("UPDATING KNOWN GUESTS")
    print("="*60)
    print()

    if guests_in_title:
        print(f"ℹ️  {len(guests_in_title)} guest(s) already in episode title (will be auto-detected):")
        for name in guests_in_title:
            print(f"  • {name}")
        print()

    if guests_to_add:
        print("⚠️  Guests NOT in known_guests.json (add these first):")
        print()
        for guest in guests_to_add:
            print(f'  • {guest["name"]}')
        print()

        # Ask if user wants to add them now
        response = input(f"Add {len(guests_to_add)} missing guest(s) now? (Y/n): ").strip().lower()

        if response != 'n' and response != 'no':
            import subprocess
            added_count = 0

            for guest in guests_to_add:
                print(f"\n{'='*60}")
                print(f"Adding guest {added_count + 1}/{len(guests_to_add)}: {guest['name']}")
                print(f"{'='*60}\n")

                # Run lookup_guest.py for this guest
                try:
                    result = subprocess.run(
                        ['uv', 'run', 'python3', 'lookup_guest.py', guest['name']],
                        check=False
                    )

                    if result.returncode == 0:
                        added_count += 1
                    else:
                        print(f"\n⚠️  Failed to add {guest['name']}")
                        response = input("Continue with next guest? (Y/n): ").strip().lower()
                        if response == 'n' or response == 'no':
                            break

                except KeyboardInterrupt:
                    print("\n\nInterrupted by user")
                    break

            print(f"\n✓ Added {added_count}/{len(guests_to_add)} guest(s)")

            if added_count < len(guests_to_add):
                print("\n⚠️  Some guests were not added. Run the script again to continue.")
                sys.exit(1)

            # Reload known guests data
            known_guests, aliases = load_known_guests()

            # Re-process the guests that were just added
            guests_to_add = []
            for guest in guests:
                name = guest['name']
                canonical_name = aliases.get(name, name)

                if canonical_name not in known_guests and name not in title and canonical_name not in title:
                    guests_to_add.append({
                        'name': name,
                        'img': guest.get('imageUrl'),
                        'href': guest.get('url')
                    })

            if guests_to_add:
                print("\n❌ Some guests are still missing. Please add them manually.")
                sys.exit(1)

            # Update already_in_feed list
            already_in_feed = []
            for guest in guests:
                name = guest['name']
                canonical_name = aliases.get(name, name)

                if name not in title and canonical_name not in title and canonical_name in known_guests:
                    already_in_feed.append(canonical_name)
        else:
            print("\n❌ Cannot add extra_episodes until all guests are in known_guests.json")
            print("\nTo add manually, run:")
            for guest in guests_to_add:
                print(f'  uv run python3 lookup_guest.py "{guest["name"]}"')
            sys.exit(1)

    # Update known_guests.json with extra_episodes
    guests_updated = 0
    guests_already_had_episode = 0

    # Reload the full data from file to avoid race conditions
    with open('cdspill_known_guests.json', 'r', encoding='utf-8') as f:
        full_data = json.load(f)

    for name in already_in_feed:
        # Check if this guest already has this episode in extra_episodes (from file)
        extra_eps = full_data['guests'].get(name, {}).get('extra_episodes', [])
        has_episode = any(ep['guid'] == guid for ep in extra_eps)

        if has_episode:
            print(f'  ⏭️  {name} - already has this episode')
            guests_already_had_episode += 1
        else:
            # Add the episode to extra_episodes
            if 'extra_episodes' not in full_data['guests'][name]:
                full_data['guests'][name]['extra_episodes'] = []

            # Create note with episode number if available
            note = title
            if episode_num:
                # Check if title already has episode number
                if f'(#{episode_num})' not in title:
                    note = f"{title} (#{episode_num})"

            full_data['guests'][name]['extra_episodes'].append({
                'guid': guid,
                'note': note
            })
            print(f'  ✓ {name} - added to extra_episodes')
            guests_updated += 1

    if guests_updated > 0:
        # Sort extra_episodes by episode number for each guest
        import re
        for guest_name, guest_data in full_data['guests'].items():
            if 'extra_episodes' in guest_data:
                def get_episode_num(ep):
                    # Extract episode number from note (e.g., "Title (#125)" -> 125)
                    note = ep.get('note', '')
                    match = re.search(r'\(#(\d+)\)', note)
                    if match:
                        return int(match.group(1))
                    return -1  # Put episodes without number at the end

                guest_data['extra_episodes'].sort(key=get_episode_num, reverse=True)

        # Sort guests and aliases alphabetically
        full_data['guests'] = dict(sorted(full_data['guests'].items()))
        full_data['aliases'] = dict(sorted(full_data.get('aliases', {}).items()))

        with open('cdspill_known_guests.json', 'w', encoding='utf-8') as f:
            json.dump(full_data, f, indent=2, ensure_ascii=False)
            f.write('\n')  # Add trailing newline

        print()
        print("="*60)
        print(f"✓ Updated cdspill_known_guests.json")
        print(f"  • {guests_updated} guest(s) updated")
        if guests_already_had_episode > 0:
            print(f"  • {guests_already_had_episode} guest(s) already had this episode")
        if guests_in_title:
            print(f"  • {len(guests_in_title)} guest(s) skipped (already in episode title)")
        print("="*60)
    elif guests_already_had_episode > 0 or guests_in_title:
        print()
        print("="*60)
        print("No updates needed")
        if guests_already_had_episode > 0:
            print(f"  • {guests_already_had_episode} guest(s) already have this episode")
        if guests_in_title:
            print(f"  • {len(guests_in_title)} guest(s) in episode title (auto-detected)")
        print("="*60)

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
