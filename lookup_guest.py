#!/usr/bin/env python3
"""
Look up guest information from Podchaser and add to cdspill_known_guests.json

The script automatically detects when the searched name differs from the Podchaser name
and prompts to add the searched name as an alias.

Usage:
    uv run python3 lookup_guest.py "Guest Name"
    uv run python3 lookup_guest.py "Jan Anders Ekroll"  # Will suggest alias if Podchaser has "Anders Ekroll"
    uv run python3 lookup_guest.py "Guest Name" --alias "Short Name"  # Manual alias
"""

import sys

from dotenv import load_dotenv

from src.common.guest_config import (
    KNOWN_GUESTS_PATH,
    load_known_guests_data,
    save_known_guests,
)
from src.enrichment.podchaser_api import from_env

load_dotenv()


def main():
    if len(sys.argv) < 2:
        print("Usage: uv run python3 lookup_guest.py 'Guest Name' [--alias 'Short Name']")
        sys.exit(1)

    guest_name = sys.argv[1]
    alias = None

    # Check for --alias flag
    if len(sys.argv) >= 4 and sys.argv[2] == '--alias':
        alias = sys.argv[3]

    # Authenticate
    print(f"🔍 Searching Podchaser for: {guest_name}")
    print("="*60)
    client = from_env(required=True)

    # Search for creator
    creators = client.search_creator(guest_name, first=5)

    if not creators:
        print(f"\n❌ No results found for '{guest_name}'")
        sys.exit(1)

    print(f"\n✓ Found {len(creators)} result(s):\n")

    for i, creator in enumerate(creators, 1):
        print(f"{i}. {creator['name']}")
        if creator.get('imageUrl'):
            print(f"   Image: ✓")
        else:
            print(f"   Image: ✗")
        print(f"   URL: {creator.get('url', 'N/A')}")
        print()

    # Ask user to select
    if len(creators) == 1:
        choice = 1
        print(f"Auto-selecting the only result...")
    else:
        choice = input(f"Select creator (1-{len(creators)}, or 0 to cancel): ").strip()
        if choice == '0' or not choice:
            print("Cancelled")
            sys.exit(0)

        try:
            choice = int(choice)
            if choice < 1 or choice > len(creators):
                print("Invalid choice")
                sys.exit(1)
        except ValueError:
            print("Invalid choice")
            sys.exit(1)

    selected = creators[choice - 1]

    # Load known_guests.json
    known_guests_file = str(KNOWN_GUESTS_PATH)

    if not KNOWN_GUESTS_PATH.exists():
        print(f"❌ File not found: {known_guests_file}")
        sys.exit(1)
    known_guests_data = load_known_guests_data()

    # Check if this person already exists (by href)
    selected_href = selected.get('url')
    existing_guest_name = None

    if selected_href:
        for guest_name_in_file, guest_data in known_guests_data['guests'].items():
            if guest_data.get('href') == selected_href:
                existing_guest_name = guest_name_in_file
                break

    if existing_guest_name:
        print(f"\n✓ This person already exists as: '{existing_guest_name}'")

        # If searched name differs, add as alias
        if guest_name != existing_guest_name:
            print(f"\n⚠️  Searched for: '{guest_name}'")
            print(f"   Already exists as: '{existing_guest_name}'")
            print()
            response = input(f"Add '{guest_name}' as alias for '{existing_guest_name}'? (Y/n): ").strip().lower()
            if response != 'n' and response != 'no':
                alias = guest_name
                canonical_name = existing_guest_name
            else:
                print("No changes made")
                sys.exit(0)
        else:
            print("Guest already in database, no changes needed")
            sys.exit(0)
    else:
        # New guest - check if searched name differs from found name (potential alias)
        canonical_name = selected['name']

        if not alias and guest_name != selected['name']:
            print(f"\n⚠️  Search name differs from Podchaser name:")
            print(f"   Searched for: '{guest_name}'")
            print(f"   Found on Podchaser: '{selected['name']}'")
            print()
            response = input(f"Add '{guest_name}' as alias for '{selected['name']}'? (Y/n): ").strip().lower()
            if response != 'n' and response != 'no':
                alias = guest_name
                print(f"✓ Will add alias: '{alias}' → '{selected['name']}'")

        # Add guest data
        guest_data = {}
        if selected.get('imageUrl'):
            guest_data['img'] = selected['imageUrl']
        if selected.get('url'):
            guest_data['href'] = selected['url']

        known_guests_data['guests'][canonical_name] = guest_data
        print(f"\n✓ Adding new guest: '{canonical_name}'")

    # Add alias if set
    if alias:
        known_guests_data['aliases'][alias] = canonical_name
        print(f"✓ Adding alias: '{alias}' → '{canonical_name}'")

    # Save
    save_known_guests(known_guests_data)

    if existing_guest_name:
        print(f"\n✓ Updated {known_guests_file}:")
        print(f"   Guest: {canonical_name}")
        if alias:
            print(f"   Added alias: {alias}")
    else:
        print(f"\n✓ Added to {known_guests_file}:")
        print(f"   Name: {canonical_name}")
        if known_guests_data['guests'][canonical_name].get('img'):
            print(f"   Image: ✓")
        if known_guests_data['guests'][canonical_name].get('href'):
            print(f"   Profile: {known_guests_data['guests'][canonical_name]['href']}")
        if alias:
            print(f"   Alias: {alias}")

    print(f"\nNext: Run 'uv run enrich_cdspill.py' to use the new guest data")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled by user")
        sys.exit(1)
