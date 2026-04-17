#!/usr/bin/env python3
"""
List all podcast episodes sorted by length.

Reads the cd SPILL feed and prints every episode with its duration,
sorted from longest to shortest (default) or shortest to longest.

Usage:
    uv run python3 list_episodes_by_length.py            # longest first
    uv run python3 list_episodes_by_length.py --asc      # shortest first
    uv run python3 list_episodes_by_length.py --no-bonus # exclude bonus episodes
"""

import argparse
from typing import List, Tuple

from lxml import etree

from src.common.feed_loader import load_feed


def format_duration(seconds: int) -> str:
    """Format a duration given in seconds as H:MM:SS or M:SS."""
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def extract_episodes(feed_xml: str) -> List[Tuple[str, int, str]]:
    """
    Extract (title, duration_seconds, episode_type) for every item.

    Episodes without a parseable duration are skipped with a warning.
    """
    root = etree.fromstring(feed_xml.encode('utf-8'))
    ns = {'itunes': 'http://www.itunes.com/dtds/podcast-1.0.dtd'}
    episodes: List[Tuple[str, int, str]] = []

    for item in root.findall('.//item'):
        title_elem = item.find('title')
        duration_elem = item.find('itunes:duration', ns)
        type_elem = item.find('itunes:episodeType', ns)

        title = title_elem.text if title_elem is not None and title_elem.text else '(uten tittel)'
        ep_type = type_elem.text if type_elem is not None and type_elem.text else 'full'

        if duration_elem is None or not duration_elem.text:
            print(f"⚠ Mangler varighet: {title}")
            continue

        raw = duration_elem.text.strip()
        try:
            if ':' in raw:
                parts = [int(p) for p in raw.split(':')]
                seconds = 0
                for part in parts:
                    seconds = seconds * 60 + part
            else:
                seconds = int(raw)
        except ValueError:
            print(f"⚠ Kunne ikke tolke varighet '{raw}' for: {title}")
            continue

        episodes.append((title, seconds, ep_type))

    return episodes


def print_episodes(episodes: List[Tuple[str, int, str]], ascending: bool):
    """Print episodes sorted by duration."""
    episodes_sorted = sorted(episodes, key=lambda x: x[1], reverse=not ascending)

    print()
    print("=" * 95)
    direction = "KORTEST TIL LENGST" if ascending else "LENGST TIL KORTEST"
    print(f"CD SPILL EPISODER SORTERT ETTER LENGDE ({direction})")
    print("=" * 95)
    print(f"{'#':<5} {'Varighet':<10} {'Type':<7} {'Tittel'}")
    print("-" * 95)

    for rank, (title, seconds, ep_type) in enumerate(episodes_sorted, start=1):
        print(f"{rank:<5} {format_duration(seconds):<10} {ep_type:<7} {title}")

    total_seconds = sum(s for _, s, _ in episodes_sorted)
    longest = max(episodes_sorted, key=lambda x: x[1])
    shortest = min(episodes_sorted, key=lambda x: x[1])
    avg = total_seconds // len(episodes_sorted) if episodes_sorted else 0

    print()
    print("=" * 95)
    print(f"Antall episoder:    {len(episodes_sorted)}")
    print(f"Total spilletid:    {format_duration(total_seconds)}")
    print(f"Gjennomsnitt:       {format_duration(avg)}")
    print(f"Lengste episode:    {format_duration(longest[1])} — {longest[0]}")
    print(f"Korteste episode:   {format_duration(shortest[1])} — {shortest[0]}")
    print()


def main():
    parser = argparse.ArgumentParser(description="List cd SPILL episodes by length")
    parser.add_argument('--asc', action='store_true',
                        help='Sort shortest to longest (default is longest first)')
    parser.add_argument('--no-bonus', action='store_true',
                        help='Exclude bonus episodes')
    args = parser.parse_args()

    feed_xml = load_feed(use_cache=True)
    episodes = extract_episodes(feed_xml)

    if args.no_bonus:
        before = len(episodes)
        episodes = [e for e in episodes if e[2] != 'bonus']
        print(f"✓ Ekskluderte {before - len(episodes)} bonusepisoder")

    print_episodes(episodes, ascending=args.asc)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nAvbrutt av bruker")
    except Exception as e:
        print(f"\n\n❌ Feil: {e}")
        import traceback
        traceback.print_exc()
