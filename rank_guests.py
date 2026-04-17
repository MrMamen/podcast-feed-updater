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

from collections import defaultdict
from typing import Dict

from lxml import etree

from src.common.feed_loader import load_feed
from src.common.guest_config import load_known_guests, resolve_alias
from src.common.podcast_utils import extract_guests_from_title, is_bonus_episode


def extract_guests_from_titles(feed_xml: str, aliases: Dict) -> Dict[str, int]:
    """
    Count canonical guest names in episode titles (bonus episodes excluded).
    """
    root = etree.fromstring(feed_xml.encode('utf-8'))
    guest_counter: Dict[str, int] = defaultdict(int)

    for item in root.findall('.//item'):
        title_elem = item.find('title')
        if title_elem is None or not title_elem.text:
            continue

        title = title_elem.text
        if is_bonus_episode(title):
            continue

        for guest_name in extract_guests_from_title(title):
            canonical_name = resolve_alias(guest_name, aliases)
            guest_counter[canonical_name] += 1

    return dict(guest_counter)


def count_extra_episodes(known_guests: Dict, aliases: Dict) -> Dict[str, int]:
    """Count contributions per guest from manually added extra_episodes."""
    extra_counter: Dict[str, int] = defaultdict(int)

    for guest_name, guest_data in known_guests.items():
        canonical_name = resolve_alias(guest_name, aliases)
        for episode in guest_data.get('extra_episodes', []):
            note = episode.get('note', '')
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
    print(f"✓ Lastet {len(known_guests)} kjente gjester og {len(aliases)} alias")

    # Load feed from local cache
    feed_xml = load_feed(use_cache=True)

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
