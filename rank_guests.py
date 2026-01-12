#!/usr/bin/env python3
"""
Rank podcast guests by number of appearances.

Two types of appearances:
1. Full guest (mentioned in episode title) - guest is present for the entire episode
2. Contribution (manually added) - guest has a contribution but not present for entire episode

Bonus episodes are excluded from all counts.
Results are grouped by number of full appearances and sorted by full appearances first.

Usage:
    uv run python3 rank_guests.py
"""

import json
import re
from collections import defaultdict
from typing import Dict, Tuple

import requests
from lxml import etree


def fetch_feed() -> str:
    """Fetch the cd SPILL feed from Podbean."""
    print("📡 Henter feed fra Podbean...")
    response = requests.get("https://feed.podbean.com/cdspill/feed.xml")
    response.raise_for_status()
    print("✓ Feed hentet")
    return response.text


def load_known_guests() -> Tuple[Dict, Dict]:
    """Load known guests and aliases from JSON file."""
    try:
        with open('cdspill_known_guests.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            guests = data.get('guests', {})
            aliases = data.get('aliases', {})
            print(f"✓ Lastet {len(guests)} kjente gjester og {len(aliases)} alias")
            return guests, aliases
    except FileNotFoundError:
        print("⚠ cdspill_known_guests.json ikke funnet")
        return {}, {}


def normalize_name(name: str, aliases: Dict) -> str:
    """
    Normalize guest name using aliases.

    Args:
        name: The name to normalize
        aliases: Dict mapping name variations to canonical names

    Returns:
        Canonical name
    """
    return aliases.get(name, name)


def is_bonus_episode(title: str) -> bool:
    """Check if episode is a bonus episode."""
    return 'Bonus' in title or 'bonus' in title


def extract_guests_from_titles(feed_xml: str, aliases: Dict) -> Dict[str, int]:
    """
    Extract guest names from episode titles using pattern "med [Guest Name]".
    Excludes bonus episodes.

    Args:
        feed_xml: The RSS feed XML as string
        aliases: Dict mapping name variations to canonical names

    Returns:
        Dict with guest names and their full appearance counts
    """
    root = etree.fromstring(feed_xml.encode('utf-8'))
    items = root.findall('.//item')

    guest_counter = defaultdict(int)
    pattern = r'med (.+?)(?:\s*\(|$)'

    for item in items:
        title_elem = item.find('title')
        if title_elem is None or not title_elem.text:
            continue

        title = title_elem.text

        # Skip bonus episodes
        if is_bonus_episode(title):
            continue

        # Search for pattern "med [Guest Name]"
        match = re.search(pattern, title)
        if match:
            guest_text = match.group(1)

            # Split multiple guests separated by " og "
            guest_names = [g.strip() for g in guest_text.split(' og ')]

            for guest_name in guest_names:
                # Normalize name using aliases
                canonical_name = normalize_name(guest_name, aliases)
                guest_counter[canonical_name] += 1

    return dict(guest_counter)


def count_extra_episodes(known_guests: Dict, aliases: Dict) -> Dict[str, int]:
    """
    Count guest contributions from manually added extra_episodes.
    Excludes bonus episodes.

    Args:
        known_guests: Dict of known guests with their metadata
        aliases: Dict mapping name variations to canonical names

    Returns:
        Dict with guest names and their contribution counts
    """
    extra_counter = defaultdict(int)

    for guest_name, guest_data in known_guests.items():
        # Normalize name
        canonical_name = normalize_name(guest_name, aliases)

        # Count extra episodes (excluding bonus episodes)
        extra_episodes = guest_data.get('extra_episodes', [])
        for episode in extra_episodes:
            note = episode.get('note', '')
            # Skip bonus episodes
            if not is_bonus_episode(note):
                extra_counter[canonical_name] += 1

    return dict(extra_counter)


def print_ranking(full_guests: Dict[str, int], contributions: Dict[str, int]):
    """
    Print guest ranking table grouped by full appearance count.

    Args:
        full_guests: Dict with guest names and full appearance counts
        contributions: Dict with guest names and contribution counts
    """
    # Combine all unique guest names
    all_guests = set(full_guests.keys()) | set(contributions.keys())

    if not all_guests:
        print("Ingen gjester funnet!")
        return

    # Create list of tuples: (name, full_count, contribution_count, total)
    guest_data = []
    for name in all_guests:
        full_count = full_guests.get(name, 0)
        contrib_count = contributions.get(name, 0)
        total = full_count + contrib_count
        guest_data.append((name, full_count, contrib_count, total))

    # Sort by full appearances (descending), then contributions (descending), then name (ascending)
    guest_data.sort(key=lambda x: (-x[1], -x[2], x[0]))

    # Group by full appearance count
    from itertools import groupby
    grouped = groupby(guest_data, key=lambda x: x[1])

    # Print header
    print()
    print("="*85)
    print("GJESTESTATISTIKK ETTER ANTALL FULLSTENDIGE OPPTREDENER")
    print("="*85)
    print()

    rank = 1
    for full_count, group in grouped:
        guests_in_group = list(group)

        # Print group header
        if full_count > 0:
            print(f"\n{full_count} FULLSTENDIGE OPPTREDENER:")
        else:
            print(f"\nKUN BIDRAG:")
        print("-"*85)
        print(f"{'#':<6} {'Full':<6} {'Bidrag':<8} {'Totalt':<7} {'Gjest'}")
        print("-"*85)

        # Print guests in this group
        for name, full, contrib, total in guests_in_group:
            print(f"{rank:<6} {full:<6} {contrib:<8} {total:<7} {name}")
            rank += 1

    # Print summary
    print()
    print("="*85)
    total_full = sum(full_guests.values())
    total_contrib = sum(contributions.values())
    print(f"Totalt: {len(all_guests)} unike gjester")
    print(f"  • {total_full} fullstendige opptredener")
    print(f"  • {total_contrib} bidrag")
    print(f"  • {total_full + total_contrib} totale opptredener")
    print()


def main():
    """Main function."""
    print("="*85)
    print("CD SPILL GJESTESTATISTIKK")
    print("="*85)
    print()

    # Load known guests and aliases
    known_guests, aliases = load_known_guests()

    # Fetch feed
    feed_xml = fetch_feed()

    print()
    print("📊 Analyserer gjesteopptredener (bonusepisoder ekskludert)...")
    print()

    # Count guests from episode titles (full appearances)
    full_guests = extract_guests_from_titles(feed_xml, aliases)
    print(f"✓ Fant {sum(full_guests.values())} fullstendige opptredener (i episodetitler)")

    # Count manually added extra episodes (contributions)
    contributions = count_extra_episodes(known_guests, aliases)
    print(f"✓ Fant {sum(contributions.values())} bidrag (manuelt lagt til)")

    # Print ranking
    print_ranking(full_guests, contributions)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nAvbrutt av bruker")
    except Exception as e:
        print(f"\n\n❌ Feil: {e}")
        import traceback
        traceback.print_exc()
