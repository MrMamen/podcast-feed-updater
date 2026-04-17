#!/usr/bin/env python3
"""
List all podcast episodes with their duration.

Reads the cd SPILL feed and prints every episode with its duration,
sorted from longest to shortest (default), shortest to longest, or in
feed order (unsorted).

Usage:
    uv run python3 list_episodes_by_length.py            # longest first
    uv run python3 list_episodes_by_length.py --asc      # shortest first
    uv run python3 list_episodes_by_length.py --no-sort  # feed order
    uv run python3 list_episodes_by_length.py --no-bonus # exclude bonus episodes
"""

import argparse
import os
import sys
from typing import List, Tuple

from lxml import etree

from src.common.feed_loader import load_feed


def _colors_enabled() -> bool:
    """Return True if we should emit ANSI color codes."""
    if os.environ.get('NO_COLOR'):
        return False
    return sys.stdout.isatty()


COLORS_ENABLED = _colors_enabled()

RESET = "\033[0m" if COLORS_ENABLED else ""
BOLD = "\033[1m" if COLORS_ENABLED else ""
DIM = "\033[2m" if COLORS_ENABLED else ""
YELLOW = "\033[33m" if COLORS_ENABLED else ""
GREEN = "\033[32m" if COLORS_ENABLED else ""
RED = "\033[31m" if COLORS_ENABLED else ""


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


def print_episodes(episodes: List[Tuple[str, int, str]], sort_mode: str):
    """
    Print episodes. ``sort_mode`` is one of ``'desc'`` (longest first),
    ``'asc'`` (shortest first) or ``'none'`` (feed order, unsorted).
    """
    if sort_mode == 'asc':
        episodes_listed = sorted(episodes, key=lambda x: x[1])
        heading = "SORTERT ETTER LENGDE (KORTEST TIL LENGST)"
    elif sort_mode == 'desc':
        episodes_listed = sorted(episodes, key=lambda x: x[1], reverse=True)
        heading = "SORTERT ETTER LENGDE (LENGST TIL KORTEST)"
    else:
        episodes_listed = list(episodes)
        heading = "I FEED-REKKEFØLGE (NYESTE FØRST)"

    print()
    print("=" * 95)
    print(f"CD SPILL EPISODER {heading}")
    print("=" * 95)
    print(f"{'#':<5} {'Varighet':<10} {'Type':<7} {'Tittel'}")
    print("-" * 95)

    # Identify the single longest and shortest episodes so they can be
    # highlighted independently of the current sort order.
    longest_id = id(max(episodes_listed, key=lambda x: x[1])) if episodes_listed else None
    shortest_id = id(min(episodes_listed, key=lambda x: x[1])) if episodes_listed else None

    for rank, episode in enumerate(episodes_listed, start=1):
        title, seconds, ep_type = episode
        display_type = _display_type(ep_type)
        line = f"{rank:<5} {format_duration(seconds):<10} {display_type:<7} {title}"
        prefix = ""

        if id(episode) == longest_id:
            prefix = BOLD + GREEN
        elif id(episode) == shortest_id:
            prefix = BOLD + RED
        elif ep_type == 'bonus':
            prefix = YELLOW

        suffix = RESET if prefix else ""
        print(f"{prefix}{line}{suffix}")

    total_seconds = sum(s for _, s, _ in episodes_listed)
    avg = total_seconds // len(episodes_listed) if episodes_listed else 0

    print()
    print("=" * 95)
    _print_summary_line("Antall episoder", str(len(episodes_listed)))
    _print_summary_line("Total spilletid", format_duration(total_seconds))
    _print_summary_line("Gjennomsnitt", format_duration(avg))

    if episodes_listed:
        overall_longest = max(episodes_listed, key=lambda x: x[1])
        overall_shortest = min(episodes_listed, key=lambda x: x[1])
        _print_extreme("Lengste", overall_longest)
        _print_extreme("Korteste", overall_shortest)

        # Only show per-type entries when they differ from the overall extremes
        for ep_type in ('full', 'bonus'):
            subset = [e for e in episodes_listed if e[2] == ep_type]
            if not subset:
                continue
            type_longest = max(subset, key=lambda x: x[1])
            type_shortest = min(subset, key=lambda x: x[1])
            if type_longest != overall_longest:
                _print_extreme(f"Lengste {_display_type(ep_type)}", type_longest)
            if type_shortest != overall_shortest:
                _print_extreme(f"Korteste {_display_type(ep_type)}", type_shortest)
    print()


SUMMARY_LABEL_WIDTH = 20


def _display_type(ep_type: str) -> str:
    """Translate the raw RSS episodeType into the label we show in the UI."""
    return 'normal' if ep_type == 'full' else ep_type


def _print_summary_line(label: str, value: str) -> None:
    print(f"{label + ':':<{SUMMARY_LABEL_WIDTH}}{value}")


def _print_extreme(label: str, episode: Tuple[str, int, str]) -> None:
    """Print one extreme entry with a label like 'Lengste' or 'Korteste bonus'."""
    title, seconds, _ = episode
    _print_summary_line(label, f"{format_duration(seconds)} — {title}")


def main():
    parser = argparse.ArgumentParser(description="List cd SPILL episodes by length")
    order = parser.add_mutually_exclusive_group()
    order.add_argument('--asc', action='store_true',
                       help='Sort shortest to longest (default is longest first)')
    order.add_argument('--no-sort', action='store_true',
                       help='Keep feed order (newest first); do not sort by length')
    parser.add_argument('--no-bonus', action='store_true',
                        help='Exclude bonus episodes')
    args = parser.parse_args()

    feed_xml = load_feed(use_cache=True)
    episodes = extract_episodes(feed_xml)

    if args.no_bonus:
        before = len(episodes)
        episodes = [e for e in episodes if e[2] != 'bonus']
        print(f"✓ Ekskluderte {before - len(episodes)} bonusepisoder")

    if args.no_sort:
        sort_mode = 'none'
    elif args.asc:
        sort_mode = 'asc'
    else:
        sort_mode = 'desc'

    print_episodes(episodes, sort_mode=sort_mode)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nAvbrutt av bruker")
    except Exception as e:
        print(f"\n\n❌ Feil: {e}")
        import traceback
        traceback.print_exc()
