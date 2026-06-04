#!/usr/bin/env python3
"""
Build an experimental podcast feed (Podchaser-free) for probing how podcast
apps — Overcast in particular — react to feed updates, ordering and episode
re-numbering.

It republishes a subset of cd SPILL episodes under a separate feed identity
(own title + podcast:guid, so apps treat it as a distinct subscription). Real
enclosures, guids and pubDates are kept, so episodes download and are tracked
stably across rebuilds.

To mirror the Tiltcast risk (where inserting an episode re-numbers the others),
the test feed carries **no season tags** and **fictional, position-based episode
numbers** (newest = 1, counted from the top). So an episode's number shifts every
time something is added/inserted above it: the one you just added is #1, then
becomes #2 when a newer one arrives. If the app keys on guid it shouldn't care.

Knobs (no code changes between runs):
  --episodes N   include the N NEWEST episodes (newest first)
  --pin EPNUM    also include the source episode numbered EPNUM, forced to feed
                 position #2 — pick an OLDER one to test an out-of-order insert
                 that re-numbers the episodes below it
  --fresh-pin    date the pinned episode to NOW — test whether a recent-dated new
                 guid triggers push/download (vs an old-dated one that doesn't)
  --type         episodic | serial

Example probe across runs:
    uv run build_experiment_feed.py --episodes 4
    uv run build_experiment_feed.py --episodes 4 --pin 100   # inserts an older one at #2

Costs no query points (reads the public cd SPILL feed). Deploy via the
"Build Experiment Feed" workflow.
"""

import argparse
import os
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime

import requests
from lxml import etree

ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
PODCAST = "https://podcastindex.org/namespace/1.0"
ATOM = "http://www.w3.org/2005/Atom"

# Enriched feed has itunes:episode numbers, needed so --pin can find an episode.
DEFAULT_SOURCE = "https://mrmamen.github.io/podcast-feed-updater/cdspill-enriched.xml"
DEFAULT_TITLE = "Tiltcast feed-eksperiment (TEST)"
# Stable, deterministic guid so every rebuild is recognized as the same feed.
EXPERIMENT_GUID = str(uuid.uuid5(uuid.NAMESPACE_URL,
                                 "podcast-feed-updater/experiment"))
_EPOCH = parsedate_to_datetime("Thu, 01 Jan 1970 00:00:00 +0000")


def load_source(source: str) -> etree._Element:
    """Parse the source feed from a local path or URL into an <rss> element."""
    if source.startswith(("http://", "https://")):
        print(f"Fetching source feed: {source}")
        content = requests.get(source, timeout=30).content
    else:
        print(f"Loading source feed: {source}")
        with open(source, "rb") as f:
            content = f.read()
    return etree.fromstring(content)


def _pubdate(item: etree._Element):
    try:
        return parsedate_to_datetime(item.findtext("pubDate"))
    except (TypeError, ValueError):
        return _EPOCH


def _source_episode_no(item: etree._Element):
    return item.findtext(f"{{{ITUNES}}}episode")


def set_text(channel, qname, text):
    """Set (or create) a channel child element's text."""
    el = channel.find(qname)
    if el is None:
        el = etree.SubElement(channel, qname)
    el.text = text
    return el


def main():
    parser = argparse.ArgumentParser(description="Build an experiment feed from cd SPILL")
    parser.add_argument("--episodes", type=int, default=3,
                        help="Number of NEWEST episodes to include")
    parser.add_argument("--pin", default=None,
                        help="Comma-separated source episode number(s) to include, pinned "
                             "from feed position #2 onward")
    parser.add_argument("--fresh-pin", action="store_true",
                        help="Date the pinned episode to now — test whether a recent-dated "
                             "new guid triggers push/download (vs an old-dated one)")
    parser.add_argument("--pin-date", default=None,
                        help="Date the pinned episode to YYYY-MM-DD (e.g. a recent event "
                             "day) — generalizes --fresh-pin to test the recency threshold")
    parser.add_argument("--type", choices=["episodic", "serial"], default="episodic")
    parser.add_argument("--image-url", default=None,
                        help="Channel cover image URL (default: the Tiltcast 4 cover)")
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--output", default="output/experiment.xml")
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--base-url",
                        default="https://mrmamen.github.io/podcast-feed-updater")
    args = parser.parse_args()

    root = load_source(args.source)
    channel = root.find("channel")
    if channel is None:
        raise SystemExit("No <channel> in source feed")

    items = channel.findall("item")
    by_date = sorted(items, key=_pubdate, reverse=True)  # newest first
    selected = list(by_date[:args.episodes])

    # --pin: ensure the numbered source episode(s) are included.
    pin_items = []
    if args.pin:
        for num in [p.strip() for p in str(args.pin).split(",") if p.strip()]:
            it = next((x for x in items if _source_episode_no(x) == num), None)
            if it is None:
                print(f"⚠ --pin {num}: no episode with that number in source; skipping")
            else:
                pin_items.append(it)
                if it not in selected:
                    selected.append(it)

    # Order newest-first, then force the pinned episodes to positions #2, #3, ...
    ordered = sorted(selected, key=_pubdate, reverse=True)
    for it in pin_items:
        if it in ordered:
            ordered.remove(it)
    for offset, it in enumerate(pin_items):
        ordered.insert(min(1 + offset, len(ordered)), it)

    # Re-date the pinned episode(s) to isolate whether pubDate recency gates
    # push/download. --pin-date sets a specific day; --fresh-pin uses now. With
    # several pins, stagger by a minute so they have distinct, descending dates.
    if pin_items and (args.pin_date or args.fresh_pin):
        if args.pin_date:
            base_dt = datetime.strptime(args.pin_date, "%Y-%m-%d").replace(
                hour=12, tzinfo=timezone.utc)
        else:
            base_dt = datetime.now(timezone.utc)
        for i, it in enumerate(pin_items):
            pd = it.find("pubDate")
            if pd is None:
                pd = etree.SubElement(it, "pubDate")
            pd.text = format_datetime(base_dt - timedelta(minutes=i))
            print(f"  pin date set: {it.findtext('title')[:30]!r} -> {pd.text}")

    # Strip season tags and assign fictional, position-based episode numbers
    # (newest = 1). These shift whenever an episode is added/inserted above —
    # the point of the experiment.
    for pos, it in enumerate(ordered, start=1):
        for tag in (f"{{{ITUNES}}}season", f"{{{PODCAST}}}season"):
            for el in it.findall(tag):
                it.remove(el)
        ep_el = it.find(f"{{{ITUNES}}}episode")
        if ep_el is None:
            ep_el = etree.SubElement(it, f"{{{ITUNES}}}episode")
        ep_el.text = str(pos)

    # Prune to the selected items and re-append in the desired order.
    for it in items:
        channel.remove(it)
    for it in ordered:
        channel.append(it)

    # Rewrite the channel to a distinct experiment identity.
    base = args.base_url.rstrip("/")
    self_url = f"{base}/experiment.xml"
    image_url = args.image_url or f"{base}/tiltcast-4.jpg"
    set_text(channel, "title", args.title)
    set_text(channel, "description",
             "Eksperimentell feed for å teste hvordan podkast-apper reagerer på "
             "oppdateringer, rekkefølge og episodenummerering. Subset av "
             "cd SPILL-episoder. Ikke en ekte podkast.")
    set_text(channel, "link", self_url)
    set_text(channel, f"{{{PODCAST}}}guid", EXPERIMENT_GUID)
    set_text(channel, f"{{{ITUNES}}}type", args.type)
    for link in channel.findall(f"{{{ATOM}}}link"):
        if link.get("rel") == "self":
            link.set("href", self_url)

    # Override the channel cover (otherwise it shows the source's cd SPILL art).
    itunes_img = channel.find(f"{{{ITUNES}}}image")
    if itunes_img is None:
        itunes_img = etree.SubElement(channel, f"{{{ITUNES}}}image")
    itunes_img.set("href", image_url)
    rss_img = channel.find("image")
    if rss_img is None:
        rss_img = etree.SubElement(channel, "image")
    set_text(rss_img, "url", image_url)
    set_text(rss_img, "title", args.title)
    set_text(rss_img, "link", self_url)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    etree.ElementTree(root).write(args.output, encoding="utf-8",
                                  xml_declaration=True, pretty_print=True)

    print(f"\n✓ {args.output}")
    print(f"  type: {args.type}  |  episodes: {len(ordered)} (of {len(items)} in source)")
    print("  feed order (pos = fictional itunes:episode):")
    for pos, it in enumerate(ordered, start=1):
        pin_mark = "  ← PINNED" if it in pin_items else ""
        print(f"    ep {pos}. {it.findtext('title')[:36]:36} "
              f"{it.findtext('pubDate')}{pin_mark}")
    print(f"  identity: {args.title!r}  guid={EXPERIMENT_GUID}")
    print(f"  cover: {image_url}")


if __name__ == "__main__":
    main()
