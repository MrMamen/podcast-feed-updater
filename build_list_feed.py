#!/usr/bin/env python3
"""
Build self-updating RSS feeds from a Podchaser list, configured in
podcasts/<id>/list.toml (e.g. podcasts/tiltcast/ for "Episoder fra Tiltcast i
Oslo").

Generates one combined feed (all editions) plus one feed per edition/section,
hosting cover art from podcasts/<id>/images/ on GitHub Pages. Run manually
whenever the list is updated:

    uv run build_list_feed.py [--list tiltcast]

Cost-aware: it counts the list (cheap), estimates the full query cost via the
free /cost endpoint, aborts if it would drop below the configured point floor,
and logs remaining points throughout. Source audio URLs are kept verbatim, so
cd SPILL's op3 prefix is preserved and no op3 is added to the others.

Outputs (in output/, deployed to gh-pages alongside the enriched feeds):
    <combined slug>.xml              all editions, one season per edition
    <section_prefix>1.xml .. N.xml   one feed per edition, in list order
"""

import argparse
import os
import shutil
import sys

from dotenv import load_dotenv

from src.config import OUTPUT_DIR, ConfigError, load_list
from src.enrichment.podchaser_api import from_env
from src.listfeed.feed_builder import assign_running_order_pubdates, build_feed
from src.listfeed.podchaser_list import fetch_list, resolve_list_id

load_dotenv()

GENERATOR = "podcast-feed-updater list builder v1.0"


def find_image_filename(images_dir, slug: str):
    """Return the basename of the cover image for a slug, or None if missing."""
    for ext in ("png", "jpg", "jpeg"):
        if os.path.isfile(os.path.join(images_dir, f"{slug}.{ext}")):
            return f"{slug}.{ext}"
    return None


def copy_assets(images_dir):
    """Copy cover images into output/ so they deploy to GitHub Pages."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    copied = 0
    for path in sorted(images_dir.iterdir()) if images_dir.is_dir() else []:
        if path.is_file():
            shutil.copy2(path, OUTPUT_DIR)
            copied += 1
    print(f"📷 Copied {copied} cover image(s) to {OUTPUT_DIR}/")


def image_url_for(images_dir, slug: str, base_url: str):
    """Resolve the public cover URL for a slug, warning if the file is absent."""
    filename = find_image_filename(images_dir, slug)
    if not filename:
        print(f"  ⚠ No cover image for {slug} — channel image will be omitted")
        return None
    return f"{base_url}/{filename}"


def main():
    parser = argparse.ArgumentParser(description="Build RSS feeds from a Podchaser list")
    parser.add_argument("--list", metavar="ID",
                        help="List under podcasts/<ID>/list.toml (default: LIST env var, or the only one)")
    args = parser.parse_args()
    try:
        list_cfg = load_list(args.list)
    except ConfigError as e:
        sys.exit(f"❌ {e}")
    cfg, images_dir = list_cfg.data, list_cfg.images_dir

    print("=" * 60)
    print(f"LIST FEED BUILDER: {list_cfg.id}")
    print("=" * 60)

    base_url = cfg["base_url"].rstrip("/")
    combined = cfg["combined"]
    section_prefix = cfg.get("section_prefix", f"{list_cfg.id}-")
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

    copy_assets(images_dir)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("\n🛠  Building feeds:")

    # Give each section its edition cover so the combined feed can show it
    # at the season headers (rendered by feed.xsl).
    for idx, section in enumerate(sections, start=1):
        section["image"] = image_url_for(images_dir, f"{section_prefix}{idx}", base_url)

    # Combined feed: all editions, one season each.
    build_feed(
        title=combined["title"],
        description=data.get("description"),
        language=cfg["language"],
        author=cfg["author"],
        category=cfg["category"],
        explicit=cfg.get("explicit", False),
        image_url=image_url_for(images_dir, combined["slug"], base_url),
        self_url=f"{base_url}/{combined['slug']}.xml",
        link=data.get("url") or base_url,
        generator=GENERATOR,
        last_build_raw=data.get("updatedAt"),
        sections=sections,
        podcast_type="episodic",
        include_season=True,
        output_file=os.path.join(OUTPUT_DIR, f"{combined['slug']}.xml"),
    )

    # One feed per edition, in list order: <prefix>1.xml ... <prefix>N.xml.
    newest_idx = len(sections)
    title_fallback = cfg.get("section_title_fallback", "{title} — {index}")
    section_description = cfg.get("section_description")
    for idx, section in enumerate(sections, start=1):
        slug = f"{section_prefix}{idx}"
        heading = section.get("heading")
        title = heading or title_fallback.format(title=combined["title"], index=idx)
        description = (section_description.format(heading=heading)
                       if heading and section_description else data.get("description"))
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
            image_url=image_url_for(images_dir, slug, base_url),
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
