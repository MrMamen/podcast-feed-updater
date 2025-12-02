#!/usr/bin/env python3
"""
Add guest from Podchaser URL to known_guests.json.

If the name from Podchaser doesn't match any existing guest, the user can
select the matching guest from a list using arrow keys.

Usage:
    uv run python3 add_guest_from_url.py "https://www.podchaser.com/creators/name-id"
"""

import sys
import json
import re
import requests
from dotenv import load_dotenv
import os

import inquirer

load_dotenv()


def extract_creator_info_from_url(url):
    """Extract creator ID and name from Podchaser URL."""
    # URL format: https://www.podchaser.com/creators/name-107tZxOga3
    match = re.search(r'/creators/([^/]+)-([a-zA-Z0-9]+)$', url)
    if match:
        name_slug = match.group(1)
        creator_id = match.group(2)
        # Convert slug to name (replace hyphens with spaces, capitalize)
        name = ' '.join(word.capitalize() for word in name_slug.split('-'))
        return creator_id, name

    # Alternative: just the ID
    match = re.search(r'creators/([a-zA-Z0-9]+)$', url)
    if match:
        return match.group(1), None

    return None, None


def authenticate_podchaser():
    """Authenticate with Podchaser API."""
    api_key = os.getenv('PODCHASER_API_KEY')
    api_secret = os.getenv('PODCHASER_API_SECRET')

    if not api_key or not api_secret:
        print("❌ Missing Podchaser credentials in .env file")
        print("   PODCHASER_API_KEY and PODCHASER_API_SECRET required")
        sys.exit(1)

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
        print(f"❌ Failed to authenticate: {token_data}")
        sys.exit(1)

    return token_data['data']['requestAccessToken']['access_token']


def search_creator_by_name(name, access_token):
    """Search for creator by name on Podchaser."""
    query = '''
    query {
      creators(searchTerm: "%s", first: 1) {
        data {
          name
          imageUrl
          url
        }
      }
    }
    ''' % name

    response = requests.post(
        'https://api.podchaser.com/graphql',
        json={'query': query},
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {access_token}'
        }
    )

    result = response.json()

    if 'errors' in result:
        print(f"❌ Error: {result['errors']}")
        return None

    creators = result.get('data', {}).get('creators', {}).get('data', [])
    if creators:
        return creators[0]

    return None


def normalize_name(name):
    """Normalize name for comparison (lowercase, no extra spaces)."""
    return ' '.join(name.lower().split())


def find_similar_guests(podchaser_name, known_guests):
    """Find guests with similar names in known_guests."""
    normalized_podchaser = normalize_name(podchaser_name)

    # Check for exact match
    for guest_name in known_guests.keys():
        if normalize_name(guest_name) == normalized_podchaser:
            return guest_name, True  # exact match

    # Check for partial matches (first name, last name, etc.)
    podchaser_parts = set(normalized_podchaser.split())
    similar = []

    for guest_name in known_guests.keys():
        guest_parts = set(normalize_name(guest_name).split())

        # If any name parts match
        if podchaser_parts & guest_parts:
            similar.append(guest_name)

    return similar, False


def main():
    if len(sys.argv) < 2:
        print("Usage: uv run python3 add_guest_from_url.py 'https://www.podchaser.com/creators/...'")
        sys.exit(1)

    url = sys.argv[1]

    print("="*60)
    print("ADD GUEST FROM PODCHASER URL")
    print("="*60)

    # Extract creator info from URL
    creator_id, name_from_url = extract_creator_info_from_url(url)
    if not creator_id or not name_from_url:
        print(f"❌ Invalid Podchaser URL: {url}")
        print("   Expected format: https://www.podchaser.com/creators/name-107tZxOga3")
        sys.exit(1)

    print(f"\n📋 Creator ID: {creator_id}")
    print(f"📋 Name from URL: {name_from_url}")

    # Authenticate
    print("\n🔑 Authenticating with Podchaser...")
    access_token = authenticate_podchaser()
    print("✓ Authenticated")

    # Search for creator
    print(f"🔍 Searching for '{name_from_url}'...")
    creator = search_creator_by_name(name_from_url, access_token)

    if not creator:
        print("❌ Creator not found")
        sys.exit(1)

    podchaser_name = creator['name']
    print(f"\n✓ Found: {podchaser_name}")
    if creator.get('imageUrl'):
        print(f"  📷 Image: ✓")
    if creator.get('url'):
        print(f"  🔗 URL: {creator['url']}")

    # Load known_guests
    known_guests_file = 'cdspill_known_guests.json'
    try:
        with open(known_guests_file, 'r', encoding='utf-8') as f:
            known_guests_data = json.load(f)
    except FileNotFoundError:
        print(f"❌ File not found: {known_guests_file}")
        sys.exit(1)

    guests = known_guests_data.get('guests', {})
    aliases = known_guests_data.get('aliases', {})

    # Check if already exists
    if podchaser_name in guests:
        print(f"\n✓ Guest already exists in known_guests.json: {podchaser_name}")

        # Update if missing data
        existing = guests[podchaser_name]
        updated = False

        if not existing.get('href') and creator.get('url'):
            existing['href'] = creator['url']
            updated = True
            print(f"  ✓ Added href")

        if not existing.get('img') and creator.get('imageUrl'):
            existing['img'] = creator['imageUrl']
            updated = True
            print(f"  ✓ Added img")

        if updated:
            with open(known_guests_file, 'w', encoding='utf-8') as f:
                json.dump(known_guests_data, f, indent=2, ensure_ascii=False)
            print(f"\n✓ Updated {known_guests_file}")
        else:
            print(f"  (no updates needed)")

        return

    # Check if name exists as an alias
    if podchaser_name in aliases:
        real_name = aliases[podchaser_name]
        print(f"\n✓ Name already aliased: '{podchaser_name}' → '{real_name}'")

        # Update the real guest entry
        if real_name in guests:
            existing = guests[real_name]
            updated = False

            if not existing.get('href') and creator.get('url'):
                existing['href'] = creator['url']
                updated = True
                print(f"  ✓ Added href to '{real_name}'")

            if not existing.get('img') and creator.get('imageUrl'):
                existing['img'] = creator['imageUrl']
                updated = True
                print(f"  ✓ Added img to '{real_name}'")

            if updated:
                with open(known_guests_file, 'w', encoding='utf-8') as f:
                    json.dump(known_guests_data, f, indent=2, ensure_ascii=False)
                print(f"\n✓ Updated {known_guests_file}")

        return

    # Find similar guests
    similar, is_exact = find_similar_guests(podchaser_name, guests)

    if is_exact:
        # This shouldn't happen (already checked above), but just in case
        existing_name = similar
        print(f"\n✓ Exact match found: {existing_name}")
        return

    # Present options to user
    print(f"\n🤔 Is '{podchaser_name}' the same person as any existing guest?")
    print()

    # Build options list
    options = []

    if similar and len(similar) <= 10:
        # Show similar matches first
        options.append("--- Similar names ---")
        for guest_name in sorted(similar):
            guest_info = guests[guest_name]
            status = []
            if guest_info.get('img'):
                status.append("📷")
            if guest_info.get('href'):
                status.append("🔗")
            status_str = " ".join(status) if status else "  "
            options.append(f"{status_str} {guest_name}")

        options.append("--- All guests ---")

    # Show all guests
    for guest_name in sorted(guests.keys()):
        if similar and guest_name in similar:
            continue  # Already shown above

        guest_info = guests[guest_name]
        status = []
        if guest_info.get('img'):
            status.append("📷")
        if guest_info.get('href'):
            status.append("🔗")
        status_str = " ".join(status) if status else "  "
        options.append(f"{status_str} {guest_name}")

    options.append("--- Actions ---")
    options.append("➕ Add as new guest (not a match)")
    options.append("❌ Cancel")

    # Interactive selection
    questions = [
        inquirer.List('guest',
                      message=f"Select matching guest or add as new",
                      choices=options,
                      carousel=True)
    ]

    answers = inquirer.prompt(questions)

    if not answers:
        print("\n❌ Cancelled")
        sys.exit(0)

    selected = answers['guest']

    # Handle selection
    if selected == "❌ Cancel":
        print("\n❌ Cancelled")
        sys.exit(0)

    elif selected == "➕ Add as new guest (not a match)":
        # Add as new guest
        guest_data = {}
        if creator.get('imageUrl'):
            guest_data['img'] = creator['imageUrl']
        if creator.get('url'):
            guest_data['href'] = creator['url']

        guests[podchaser_name] = guest_data

        with open(known_guests_file, 'w', encoding='utf-8') as f:
            json.dump(known_guests_data, f, indent=2, ensure_ascii=False)

        print(f"\n✓ Added new guest: {podchaser_name}")
        print(f"✓ Saved to {known_guests_file}")

    elif selected.startswith("---"):
        print("\n❌ Invalid selection")
        sys.exit(1)

    else:
        # Extract guest name from selection (remove status icons)
        existing_name = re.sub(r'^[📷🔗\s]+', '', selected).strip()

        print(f"\n✓ Matched with existing guest: {existing_name}")

        # The Podchaser name is the official name
        # The existing name in the file might be an alias used in episode titles

        if normalize_name(podchaser_name) != normalize_name(existing_name):
            # Names are different - use Podchaser name as the official one
            print(f"  ℹ️  Podchaser name '{podchaser_name}' differs from '{existing_name}'")
            print(f"  → Using Podchaser name as official, making '{existing_name}' an alias")

            # Get existing guest data
            existing_data = guests[existing_name]

            # Remove old entry
            del guests[existing_name]

            # Add with Podchaser name as the official name
            guests[podchaser_name] = existing_data

            # Update with new data from Podchaser
            if not existing_data.get('href') and creator.get('url'):
                guests[podchaser_name]['href'] = creator['url']
                print(f"  ✓ Added href")

            if not existing_data.get('img') and creator.get('imageUrl'):
                guests[podchaser_name]['img'] = creator['imageUrl']
                print(f"  ✓ Added img")

            # Create alias: old name (from feed) → official name (from Podchaser)
            aliases[existing_name] = podchaser_name
            print(f"  ✓ Created alias: '{existing_name}' → '{podchaser_name}'")

            updated = True
        else:
            # Names are the same, just update data
            existing = guests[existing_name]
            updated = False

            if not existing.get('href') and creator.get('url'):
                existing['href'] = creator['url']
                updated = True
                print(f"  ✓ Added href")

            if not existing.get('img') and creator.get('imageUrl'):
                existing['img'] = creator['imageUrl']
                updated = True
                print(f"  ✓ Added img")

        if updated:
            with open(known_guests_file, 'w', encoding='utf-8') as f:
                json.dump(known_guests_data, f, indent=2, ensure_ascii=False)
            print(f"\n✓ Updated {known_guests_file}")
        else:
            print(f"  (no updates needed)")

    print(f"\n💡 Run 'uv run enrich_cdspill.py' to use the updated data")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
