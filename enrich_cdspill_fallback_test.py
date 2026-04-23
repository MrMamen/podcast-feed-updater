#!/usr/bin/env python3
"""
Generate three test variants of the enriched feed, each missing one of the
description-like fields. Use to probe podcast client fallback behavior:
subscribe to each variant in the apps you want to test and see which field
the app falls back to.

Output:
    output/cdspill-test-no-description.xml  (no <description>)
    output/cdspill-test-no-content.xml      (no <content:encoded>)
    output/cdspill-test-no-summary.xml      (no <itunes:summary>)

Usage:
    uv run enrich_cdspill_fallback_test.py                # fetch enriched feed from GitHub Pages
    uv run enrich_cdspill_fallback_test.py --local-cache  # use output/cdspill-enriched.xml
"""

import os
import sys
import uuid
import argparse
from dotenv import load_dotenv
from src.enrichment.enricher import FeedEnricher

load_dotenv()

BASE_PUBLISH_URL = "https://mrmamen.github.io/podcast-feed-updater"

# Distinct podcast:guid per variant so clients that dedupe by feed identity
# (e.g. MediaMonkey) treat each test feed as a separate subscription.
# Generated once via uuid5 so they are stable across runs.
NAMESPACE = uuid.UUID("a550e4b5-6615-5a5d-b1d5-a371c01552a2")  # main feed guid

VARIANTS = [
    {
        "slug": "no-description",
        "field_tag": "description",
        "title_suffix": " [TEST uten description]",
        "strip_from_channel": False,  # <description> is required on RSS 2.0 channel
    },
    {
        "slug": "no-content",
        "field_tag": "{http://purl.org/rss/1.0/modules/content/}encoded",
        "title_suffix": " [TEST uten content:encoded]",
        "strip_from_channel": True,
    },
    {
        "slug": "no-summary",
        "field_tag": "{http://www.itunes.com/dtds/podcast-1.0.dtd}summary",
        "title_suffix": " [TEST uten itunes:summary]",
        "strip_from_channel": True,
    },
]


def generate_variant(source: str, slug: str, field_tag: str, title_suffix: str, strip_from_channel: bool):
    enricher = FeedEnricher(source)
    enricher.fetch_feed()

    items = enricher.channel.findall('item')
    removed = 0
    for item in items:
        el = item.find(field_tag)
        if el is not None:
            item.remove(el)
            removed += 1

    if strip_from_channel:
        channel_el = enricher.channel.find(field_tag)
        if channel_el is not None:
            enricher.channel.remove(channel_el)

    # Distinguish in podcast apps by appending to <title>
    title_elem = enricher.channel.find('title')
    if title_elem is not None and title_elem.text:
        title_elem.text = title_elem.text + title_suffix

    # Replace podcast:guid with a variant-specific one so clients that dedupe
    # on feed identity treat this as a distinct subscription.
    podcast_ns = 'https://podcastindex.org/namespace/1.0'
    guid_elem = enricher.channel.find(f'{{{podcast_ns}}}guid')
    variant_feed_guid = str(uuid.uuid5(NAMESPACE, slug))
    if guid_elem is not None:
        guid_elem.text = variant_feed_guid

    # Suffix every episode <guid> so clients that dedupe on episode guid
    # treat these as different episodes from the main feed.
    for item in items:
        item_guid = item.find('guid')
        if item_guid is not None and item_guid.text:
            item_guid.text = f"{item_guid.text}#{slug}"

    output_file = f"output/cdspill-test-{slug}.xml"
    feed_url = f"{BASE_PUBLISH_URL}/cdspill-test-{slug}.xml"

    enricher.update_atom_link(feed_url)
    enricher.update_generator(f"podcast-feed-updater v1.0 (fallback test: {slug})")
    enricher.update_lastBuildDate()

    enricher.write_feed(output_file)
    print(f"  → stripped {field_tag} from {removed} item(s), wrote {output_file}")
    print(f"     podcast:guid = {variant_feed_guid}")


def main():
    parser = argparse.ArgumentParser(
        description='Generate fallback-test feed variants'
    )
    parser.add_argument(
        '--local-cache',
        action='store_true',
        help='Use local enriched feed instead of fetching from GitHub Pages'
    )
    args = parser.parse_args()

    print("=" * 60)
    print("CD SPILL FALLBACK-TEST FEED GENERATOR")
    print("=" * 60)

    if args.local_cache:
        source = "output/cdspill-enriched.xml"
        if not os.path.exists(source):
            print(f"\n❌ Error: Enriched feed not found at {source}")
            print("   Run enrich_cdspill.py first to generate the enriched feed")
            sys.exit(1)
        print(f"\n📁 Using local enriched feed: {source}")
    else:
        source = f"{BASE_PUBLISH_URL}/cdspill-enriched.xml"
        print(f"\n🌐 Fetching enriched feed from: {source}")

    os.makedirs("output", exist_ok=True)

    for variant in VARIANTS:
        print(f"\n--- {variant['slug']} ---")
        generate_variant(source, **variant)

    print("\n" + "=" * 60)
    print("DONE!")
    print("=" * 60)
    print("\nGenerated three test feeds. Publish them (e.g. by copying to")
    print("your gh-pages branch) and subscribe in each client to see")
    print("which fallback field gets used when one is absent.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
