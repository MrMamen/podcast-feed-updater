#!/usr/bin/env python3
"""
List all episodes a specific guest has appeared in.

Two types of appearances:
1. Full guest (mentioned in episode title) - guest is present for the entire episode
2. Contribution (manually added) - guest has a contribution but not present for entire episode

Bonus episodes are excluded from all lists.

Usage:
    uv run python3 scripts/analysis/list_guest_episodes.py "Guest Name"
    uv run python3 scripts/analysis/list_guest_episodes.py "Jostein Hakestad"
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import re
import sys
from typing import Dict, List, Tuple

from lxml import etree

from src.common.feed_loader import load_feed
from src.common.guest_config import load_known_guests, resolve_alias
from src.common.podcast_utils import extract_guests_from_title, is_bonus_episode


def get_episode_info(item) -> Tuple[str, str, str]:
    """
    Extract episode information from RSS item.

    Returns:
        Tuple of (guid, title, episode_number)
    """
    guid_elem = item.find('guid')
    title_elem = item.find('title')
    episode_elem = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}episode')

    guid = guid_elem.text if guid_elem is not None else ''
    title = title_elem.text if title_elem is not None else ''
    episode_num = episode_elem.text if episode_elem is not None else ''

    return guid, title, episode_num


def find_episodes_in_titles(feed_xml: str, guest_name: str, canonical_name: str) -> List[Dict]:
    """
    Find episodes where guest is mentioned in the title.
    Excludes bonus episodes.
    """
    root = etree.fromstring(feed_xml.encode('utf-8'))
    episodes = []

    for item in root.findall('.//item'):
        guid, title, episode_num = get_episode_info(item)

        if is_bonus_episode(title):
            continue

        guest_names = extract_guests_from_title(title)
        if guest_name in guest_names or canonical_name in guest_names:
            episodes.append({
                'guid': guid,
                'title': title,
                'episode_num': episode_num,
                'source': 'full'
            })

    return episodes


def find_extra_episodes(known_guests: Dict, guest_name: str, canonical_name: str) -> List[Dict]:
    """
    Find extra episodes manually added in known_guests.json.
    Excludes bonus episodes.

    Args:
        known_guests: Dict of known guests
        guest_name: The guest name to search for
        canonical_name: The canonical name (after alias normalization)

    Returns:
        List of episode dicts with guid, title (note), episode_num, source
    """
    episodes = []

    # Check both the original name and canonical name
    for name in [guest_name, canonical_name]:
        if name in known_guests:
            extra_episodes = known_guests[name].get('extra_episodes', [])
            for ep in extra_episodes:
                note = ep.get('note', '')
                # Skip bonus episodes
                if is_bonus_episode(note):
                    continue

                # Extract episode number from note (e.g., "Spillåret 1985 (#124)" -> "124")
                episode_num = ''
                match = re.search(r'\(#(\d+)\)', note)
                if match:
                    episode_num = match.group(1)

                episodes.append({
                    'guid': ep['guid'],
                    'title': note,
                    'episode_num': episode_num,
                    'source': 'contribution'
                })

    return episodes


def merge_episodes(title_episodes: List[Dict], extra_episodes: List[Dict]) -> List[Dict]:
    """
    Merge episodes from titles and extra_episodes, removing duplicates.

    Returns:
        Sorted list of unique episodes
    """
    # Use GUID as the key to remove duplicates
    episodes_by_guid = {}

    for ep in title_episodes + extra_episodes:
        guid = ep['guid']
        if guid not in episodes_by_guid:
            episodes_by_guid[guid] = ep
        elif ep['source'] == 'title':
            # Prefer title source as it has the full title
            episodes_by_guid[guid] = ep

    # Convert back to list and sort by episode number (descending)
    episodes = list(episodes_by_guid.values())
    episodes.sort(key=lambda x: int(x['episode_num']) if x['episode_num'] else 0, reverse=True)

    return episodes


def print_episodes(guest_name: str, episodes: List[Dict]):
    """Print episodes in a formatted table, separated by type."""
    if not episodes:
        print(f"\n❌ Ingen episoder funnet for {guest_name}")
        return

    # Separate episodes by type
    full_episodes = [ep for ep in episodes if ep['source'] == 'full']
    contributions = [ep for ep in episodes if ep['source'] == 'contribution']

    print()
    print("="*80)
    print(f"EPISODER MED {guest_name.upper()}")
    print("="*80)

    # Print full guest appearances
    if full_episodes:
        print()
        print("FULLSTENDIGE OPPTREDENER (nevnt i episodetittel):")
        print("-"*80)
        print(f"{'#':<6} {'Episodetittel'}")
        print("-"*80)

        for ep in full_episodes:
            ep_num = f"#{ep['episode_num']}" if ep['episode_num'] else "N/A"
            title = ep['title']

            # Truncate title if too long
            if len(title) > 72:
                title = title[:69] + "..."

            print(f"{ep_num:<6} {title}")

    # Print contributions
    if contributions:
        print()
        print("BIDRAG (manuelt lagt til, ikke hele episoden):")
        print("-"*80)
        print(f"{'#':<6} {'Episodetittel'}")
        print("-"*80)

        for ep in contributions:
            ep_num = f"#{ep['episode_num']}" if ep['episode_num'] else "N/A"
            title = ep['title']

            # Truncate title if too long
            if len(title) > 72:
                title = title[:69] + "..."

            print(f"{ep_num:<6} {title}")

    print()
    print("-"*80)
    print(f"Totalt: {len(episodes)} opptredener")
    print(f"  • {len(full_episodes)} fullstendige opptredener")
    print(f"  • {len(contributions)} bidrag")
    print()


def main():
    """Main function."""
    if len(sys.argv) < 2:
        print("Bruk: uv run python3 scripts/analysis/list_guest_episodes.py \"Gjestenavn\"")
        sys.exit(1)

    guest_name = sys.argv[1]

    print("="*80)
    print("CD SPILL EPISODELISTE")
    print("="*80)
    print(f"\nSøker etter episoder med: {guest_name}")
    print()

    # Load known guests and aliases
    known_guests, aliases = load_known_guests()

    # Normalize name
    canonical_name = resolve_alias(guest_name, aliases)
    if canonical_name != guest_name:
        print(f"ℹ️  Bruker kanonisk navn: {canonical_name}")
        print()

    # Load feed from local cache
    feed_xml = load_feed(use_cache=True)

    # Find episodes in titles (full guest appearances)
    title_episodes = find_episodes_in_titles(feed_xml, guest_name, canonical_name)
    print(f"✓ Fant {len(title_episodes)} fullstendige opptredener (i episodetitler)")

    # Find extra episodes (contributions)
    extra_episodes = find_extra_episodes(known_guests, guest_name, canonical_name)
    print(f"✓ Fant {len(extra_episodes)} bidrag (manuelt lagt til)")
    print()
    print("ℹ️  Bonusepisoder ekskludert fra alle tellinger")

    # Merge and deduplicate
    all_episodes = merge_episodes(title_episodes, extra_episodes)

    # Print results
    print_episodes(canonical_name, all_episodes)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nAvbrutt av bruker")
    except Exception as e:
        print(f"\n\n❌ Feil: {e}")
        import traceback
        traceback.print_exc()
