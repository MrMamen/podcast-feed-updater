#!/usr/bin/env python3
"""
Build self-updating RSS feeds from the "Episoder fra Tiltcast i Oslo" Podchaser
list.

Generates one combined feed (all editions) plus one feed per edition/section,
hosting cover art from assets/tiltcast/ on GitHub Pages. Run manually whenever
the list is updated:

    uv run build_list_feed.py

Cost-aware: it counts the list (cheap), estimates the full query cost via the
free /cost endpoint, aborts if it would drop below the configured point floor,
and logs remaining points throughout. Source audio URLs are kept verbatim, so
cd SPILL's op3 prefix is preserved and no op3 is added to the others.

Outputs (in output/, deployed to gh-pages alongside the cd SPILL feeds):
    tiltcast-all.xml          all editions, one season per edition
    tiltcast-1.xml .. N.xml   one feed per edition, in list order
"""

import glob
import json
import os
import shutil
import sys

from dotenv import load_dotenv

from src.enrichment.podchaser_api import from_env
from src.listfeed.feed_builder import assign_running_order_pubdates, build_feed
from src.listfeed.podchaser_list import fetch_list, resolve_list_id

load_dotenv()

CONFIG_PATH = "config/tiltcast_list.json"
ASSETS_DIR = "assets/tiltcast"
OUTPUT_DIR = "output"
GENERATOR = "podcast-feed-updater list builder v1.0"


def find_image_filename(slug: str):
    """Return the basename of the cover image for a slug, or None if missing."""
    for ext in ("png", "jpg", "jpeg"):
        if os.path.isfile(os.path.join(ASSETS_DIR, f"{slug}.{ext}")):
            return f"{slug}.{ext}"
    return None


def copy_assets():
    """Copy cover images into output/ so they deploy to GitHub Pages."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    copied = 0
    for path in glob.glob(os.path.join(ASSETS_DIR, "tiltcast-*")):
        if os.path.isfile(path):
            shutil.copy2(path, OUTPUT_DIR)
            copied += 1
    print(f"📷 Copied {copied} cover image(s) to {OUTPUT_DIR}/")


def image_url_for(slug: str, base_url: str):
    """Resolve the public cover URL for a slug, warning if the file is absent."""
    filename = find_image_filename(slug)
    if not filename:
        print(f"  ⚠ No cover image for {slug} — channel image will be omitted")
        return None
    return f"{base_url}/{filename}"


def main():
    print("=" * 60)
    print("TILTCAST LIST FEED BUILDER")
    print("=" * 60)

    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    base_url = cfg["base_url"].rstrip("/")
    combined = cfg["combined"]
    # The combined feed and the newest edition are always episodic so podcast
    # apps auto-download new episodes; settled older editions can be serial
    # (in-order presentation, no new episodes expected). Configurable via
    # itunes_type (the type used for settled editions).
    settled_type = cfg.get("itunes_type", "serial")

    api = from_env(required=True)

    list_id = cfg.get("list_id")
    if not list_id:
        list_id = resolve_list_id(api, cfg["list_search_term"], combined.get("title"))
        if not list_id:
            sys.exit("❌ Could not resolve list id from search term")

    data = fetch_list(api, list_id, min_remaining=cfg.get("min_remaining", 12000))
    sections = data["sections"]

    print(f"\n📚 List: {data['title']!r} — {data['total']} items, "
          f"{len(sections)} section(s):")
    for idx, section in enumerate(sections, start=1):
        print(f"   {idx}. {section['heading']!r}: {len(section['episodes'])} episodes")

    # Synthesize pubDates so apps show episodes in the curated running order,
    # except the newest edition which keeps real airDate (so additions notify).
    print("\n🕒 pubDate strategy per section:")
    for entry in assign_running_order_pubdates(sections):
        anchor = entry["anchor"]
        when = f"{anchor:%Y-%m-%d}" if anchor else "real airDate"
        print(f"   {when:>12} ({entry['source']:>24}) "
              f"— {entry['count']} eps — {entry['heading']!r}")

    copy_assets()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("\n🛠  Building feeds:")

    # Combined feed: all editions, one season each.
    build_feed(
        title=combined["title"],
        description=data.get("description"),
        language=cfg["language"],
        author=cfg["author"],
        category=cfg["category"],
        explicit=cfg.get("explicit", False),
        image_url=image_url_for(combined["slug"], base_url),
        self_url=f"{base_url}/{combined['slug']}.xml",
        link=data.get("url") or base_url,
        generator=GENERATOR,
        last_build_raw=data.get("updatedAt"),
        sections=sections,
        podcast_type="episodic",
        include_season=True,
        output_file=os.path.join(OUTPUT_DIR, f"{combined['slug']}.xml"),
    )

    # One feed per edition, in list order: tiltcast-1.xml ... tiltcast-N.xml.
    newest_idx = len(sections)
    for idx, section in enumerate(sections, start=1):
        slug = f"tiltcast-{idx}"
        heading = section.get("heading")
        title = heading or f"{combined['title']} — del {idx}"
        description = (f"Live-episoder fra {heading}."
                       if heading else data.get("description"))
        # Newest edition stays episodic for auto-download; older ones use the
        # configured settled type.
        edition_type = "episodic" if idx == newest_idx else settled_type
        build_feed(
            title=title,
            description=description,
            language=cfg["language"],
            author=cfg["author"],
            category=cfg["category"],
            explicit=cfg.get("explicit", False),
            image_url=image_url_for(slug, base_url),
            self_url=f"{base_url}/{slug}.xml",
            link=data.get("url") or base_url,
            generator=GENERATOR,
            last_build_raw=data.get("updatedAt"),
            sections=[section],
            podcast_type=edition_type,
            include_season=False,
            output_file=os.path.join(OUTPUT_DIR, f"{slug}.xml"),
        )

    print("\n" + "=" * 60)
    print("DONE!")
    print("=" * 60)
    print(f"Built 1 combined + {len(sections)} edition feed(s) in {OUTPUT_DIR}/")


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
