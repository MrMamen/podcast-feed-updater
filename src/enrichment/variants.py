"""
Variant feeds built on top of the published enriched feed.

Each variant reads the main enriched feed (the published one, or the local
``output/`` copy with ``use_local``) and adapts it for one destination. Which
variants a podcast has, and their file names, is set in ``[variants.<name>]``
in podcast.toml.
"""

from __future__ import annotations

import os
import uuid

from src.common.feed_loader import resolve_enriched_source
from src.config import OUTPUT_DIR, PodcastConfig
from src.enrichment.enricher import FeedEnricher
from src.enrichment.pipeline import chapter_options, finish_feed


def _chapters_for_variant(enricher: FeedEnricher, cfg: PodcastConfig) -> None:
    # Rebuild psc:chapters inline from the chapter JSON the main feed points to.
    # output_dir=None: the chapter files (with Apple links) are hosted by the main feed
    options = chapter_options(cfg)
    options["output_dir"] = None
    enricher.convert_json_chapters_to_psc(**options)


def build_youtube(cfg: PodcastConfig, *, use_local: bool = False) -> str:
    """
    YouTube: episode numbers back in the titles and chapter timestamps in the
    descriptions (YouTube reads neither podcast:chapters nor psc:chapters).
    """
    variant = cfg.variant("youtube")
    enricher = FeedEnricher(resolve_enriched_source(cfg, use_local))
    enricher.fetch_feed()

    enricher.restore_episode_numbers_to_titles(variant.get("episode_number_format", " (#{episode})"))

    # psc:chapters are only needed to extract the timestamps from
    _chapters_for_variant(enricher, cfg)
    enricher.add_chapter_timestamps_to_description()
    enricher.remove_chapter_tags()

    return finish_feed(
        enricher, cfg,
        feed_file=variant.get("feed", f"{cfg.id}-youtube.xml"),
        generator=variant.get("generator", "podcast-feed-updater v1.0 (YouTube variant)"),
        shift_hours=variant.get("shift_latest_pubdate_hours"),
    )


def build_spotify(cfg: PodcastConfig, *, use_local: bool = False) -> str:
    """Spotify: psc:chapters inline instead of podcast:chapters (Spotify reads only psc)."""
    variant = cfg.variant("spotify")
    enricher = FeedEnricher(resolve_enriched_source(cfg, use_local))
    enricher.fetch_feed()

    # Must run before removing podcast:chapters since the JSON URL is read from there
    _chapters_for_variant(enricher, cfg)
    # The JSON reference is dead weight for Spotify and only slows down parsing
    enricher.remove_chapter_tags(remove_podcast=True, remove_psc=False)

    return finish_feed(
        enricher, cfg,
        feed_file=variant.get("feed", f"{cfg.id}-spotify.xml"),
        generator=variant.get("generator", "podcast-feed-updater v1.0 (Spotify variant)"),
        shift_hours=variant.get("shift_latest_pubdate_hours"),
    )


# One test feed per description-like field, each with that field removed, to
# probe which field a podcast client falls back to.
FALLBACK_TESTS = [
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


def _build_fallback_test(cfg: PodcastConfig, source: str, feed_prefix: str, slug: str,
                         field_tag: str, title_suffix: str, strip_from_channel: bool) -> str:
    enricher = FeedEnricher(source)
    enricher.fetch_feed()

    items = enricher.channel.findall('item')
    for item in items:
        el = item.find(field_tag)
        if el is not None:
            item.remove(el)

    if strip_from_channel:
        channel_el = enricher.channel.find(field_tag)
        if channel_el is not None:
            enricher.channel.remove(channel_el)

    # Distinguish in podcast apps by appending to <title>
    title_elem = enricher.channel.find('title')
    if title_elem is not None and title_elem.text:
        title_elem.text = title_elem.text + title_suffix

    # Distinct podcast:guid per variant (uuid5 of the main guid, so stable across
    # runs) so clients that dedupe by feed identity (e.g. MediaMonkey) treat each
    # test feed as a separate subscription.
    podcast_ns = 'https://podcastindex.org/namespace/1.0'
    guid_elem = enricher.channel.find(f'{{{podcast_ns}}}guid')
    if guid_elem is not None and cfg.guid:
        guid_elem.text = str(uuid.uuid5(uuid.UUID(cfg.guid), slug))

    # Suffix every episode <guid> so clients that dedupe on episode guid
    # treat these as different episodes from the main feed.
    for item in items:
        item_guid = item.find('guid')
        if item_guid is not None and item_guid.text:
            item_guid.text = f"{item_guid.text}#{slug}"

    feed_file = f"{feed_prefix}{slug}.xml"
    enricher.update_atom_link(f"{cfg.base_url}/{feed_file}")
    enricher.update_generator(f"podcast-feed-updater v1.0 (fallback test: {slug})")
    enricher.update_lastBuildDate(cfg.timezone)

    output_file = str(OUTPUT_DIR / feed_file)
    enricher.write_feed(output_file)
    return output_file


def build_fallback_test(cfg: PodcastConfig, *, use_local: bool = False) -> list:
    """Three test feeds, each missing one of description/content:encoded/itunes:summary."""
    variant = cfg.variant("fallback-test")
    feed_prefix = variant.get("feed_prefix", f"{cfg.id}-test-")
    source = resolve_enriched_source(cfg, use_local)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    return [_build_fallback_test(cfg, source, feed_prefix, **test) for test in FALLBACK_TESTS]


VARIANTS = {
    "youtube": build_youtube,
    "spotify": build_spotify,
    "fallback-test": build_fallback_test,
}
