#!/usr/bin/env python3
"""
Enrich a podcast feed with Podcasting 2.0 tags, as configured in
podcasts/<id>/podcast.toml.

Usage:
    uv run enrich.py                              # main enriched feed
    uv run enrich.py --local-cache                # from the local copy of the source feed
    uv run enrich.py --variant youtube            # variant built on the published enriched feed
    uv run enrich.py --variant youtube --local-cache   # ... on output/<feed> instead
    uv run enrich.py --podcast cdspill ...        # pick the podcast (needed when there are several)

Local cache:
    For the main feed, --local-cache reads .cache/<id>-original.xml (download it
    with: uv run guests.py cache). For variants it reads the enriched feed in
    output/ (run the main feed first).

Variants (see [variants] in podcast.toml):
    youtube        episode numbers in titles, chapter timestamps in descriptions
    spotify        psc:chapters inline instead of podcast:chapters
    fallback-test  three test feeds, each missing one description-like field
"""

import argparse
import sys

from dotenv import load_dotenv

from src.config import KNOWN_VARIANTS, ConfigError, add_podcast_argument, load_podcast_or_exit
from src.enrichment.enricher import FeedConflictError
from src.enrichment.pipeline import enrich
from src.enrichment.variants import VARIANTS

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Enrich a podcast feed with Podcasting 2.0 tags")
    add_podcast_argument(parser)
    parser.add_argument(
        "--variant",
        choices=sorted(KNOWN_VARIANTS),
        help="Build a variant feed from the enriched feed instead of the main feed",
    )
    parser.add_argument(
        "--local-cache",
        action="store_true",
        help="Use local copies instead of fetching from the network (for testing/development)",
    )
    args = parser.parse_args()

    cfg = load_podcast_or_exit(args.podcast)

    title = f"{cfg.name} — {args.variant}" if args.variant else cfg.name
    print("=" * 60)
    print(f"FEED ENRICHER: {title}")
    print("=" * 60)

    try:
        if args.variant:
            VARIANTS[args.variant](cfg, use_local=args.local_cache)
        else:
            enrich(cfg, use_cache=args.local_cache)
    except (ConfigError, FeedConflictError) as e:
        print(f"\n❌ {e}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("DONE!")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
