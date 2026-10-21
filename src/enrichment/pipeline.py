"""
Run the enrichment for one podcast as described by its podcast.toml.

The order of the steps is fixed here (some depend on each other, e.g. the
description footer links the Bluesky posts found earlier); the config decides
which steps run and with which values. A step whose section or option is
missing from podcast.toml is skipped.
"""

from __future__ import annotations

import os

from src.common.feed_loader import resolve_feed_source
from src.common.guest_config import (
    flatten_for_enricher,
    load_known_guests_data,
    load_permanent_staff,
)
from src.common.podcast_utils import EPISODE_NUMBER_SOURCES, season_namer
from src.config import OUTPUT_DIR, ConfigError, PodcastConfig
from src.enrichment.enricher import FeedEnricher
from src.enrichment.episode_numbers import itunes_episode_number


def _load_hosts(cfg: PodcastConfig) -> list:
    path = cfg.permanent_staff_path
    print(f"\n📋 Loading permanent staff from: {path}")
    if not path.exists():
        print(f"⚠ Config file not found: {path}")
        print("  Using empty host list")
        return []
    try:
        hosts = load_permanent_staff(path)
    except Exception as e:
        print(f"⚠ Error loading config: {e}")
        return []
    print(f"✓ Loaded {len(hosts)} permanent host(s)")
    for host in hosts:
        img_status = "📷" if 'img' in host else "  "
        href_status = "🔗" if 'href' in host else "  "
        print(f"  {img_status}{href_status} {host['name']} ({host['role']})")
    return hosts


def _load_known_guests(cfg: PodcastConfig) -> dict:
    path = cfg.known_guests_path
    print(f"\n📦 Loading known guests from: {path}")
    if not path.exists():
        print(f"⚠ File not found: {path}")
        print("  Guests will not have profile images")
        print("  Use 'uv run guests.py add <name>' to add guest data")
        return {}
    try:
        data = load_known_guests_data(path)
    except Exception as e:
        print(f"⚠ Error loading known guests: {e}")
        return {}
    guests, aliases = data['guests'], data['aliases']
    with_images = sum(1 for g in guests.values() if g.get('img'))
    print(f"✓ Loaded {len(guests)} guests ({with_images} with images) and {len(aliases)} aliases")
    return flatten_for_enricher(data)


def _episode_number_getter(cfg: PodcastConfig):
    """
    Function from item to its episode number, trying [titles]
    episode_number_source in order: "itunes" (itunes:episode) and/or "title"
    (group 1 of episode_number_pattern).
    """
    title_rules = cfg.title_rules
    sources = cfg.section("titles").get("episode_number_source", ["itunes"])
    sources = [sources] if isinstance(sources, str) else sources
    unknown = set(sources) - set(EPISODE_NUMBER_SOURCES)
    if unknown:
        raise ConfigError(f"{cfg.config_path}: [titles] episode_number_source: unknown "
                          f"{sorted(unknown)} (use {list(EPISODE_NUMBER_SOURCES)})")
    if "title" in sources and not title_rules.episode_number_re:
        raise ConfigError(f"{cfg.config_path}: episode_number_source \"title\" needs "
                          f"[titles] episode_number_pattern")

    def episode_number(item):
        for source in sources:
            if source == "itunes":
                number = itunes_episode_number(item)
            else:
                number = title_rules.episode_number(item.findtext('title'))
            if number:
                return number
        return None

    return episode_number


def chapter_options(cfg: PodcastConfig) -> dict:
    """Keyword arguments for convert_json_chapters_to_psc shared by the main feed and variants."""
    chapters = cfg.section("chapters")
    publish_path = chapters.get("publish_path", f"chapters/{cfg.id}")
    images_dir = chapters.get("images_dir")
    return {
        "chapters_dir": str(cfg.path(chapters.get("source_dir", "chapters"))),
        "images_dir": str(cfg.path(images_dir)) if images_dir else None,
        "output_dir": str(OUTPUT_DIR / publish_path),
        "base_url": f"{cfg.base_url}/{publish_path}",
        "title_rules": cfg.title_rules,
        "image_rules": chapters.get("image_rules", []),
        "cross_references": chapters.get("cross_references", []),
    }


def finish_feed(enricher: FeedEnricher, cfg: PodcastConfig, *, feed_file: str, generator: str,
                shift_hours: int | None = None) -> str:
    """Steps every feed ends with: metadata for where it is published, then write it."""
    enricher.format_podcast_elements()

    enricher.update_atom_link(f"{cfg.base_url}/{feed_file}")
    enricher.update_generator(generator)
    enricher.update_lastBuildDate(cfg.timezone)

    if shift_hours:
        enricher.shift_latest_episode_pubdate(hours=shift_hours)

    # Drop xmlns declarations on <rss> that nothing in the document uses
    enricher.prune_unused_namespaces()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_file = str(OUTPUT_DIR / feed_file)
    enricher.write_feed(output_file)
    return output_file


def enrich(cfg: PodcastConfig, *, use_cache: bool = False) -> str:
    """Build the main enriched feed for ``cfg``. Returns the output file path."""
    podcast = cfg.section("podcast")
    publish = cfg.section("publish")
    titles = cfg.section("titles")
    title_rules = cfg.title_rules

    source = resolve_feed_source(cfg, use_cache)
    if use_cache:
        print(f"\n📁 Using local cache: {source}")

    enricher = FeedEnricher(source)
    enricher.fetch_feed()

    # Fails loudly if the source feed starts carrying tags we add ourselves
    enricher.validate_no_conflicts()

    # Before the numbers are removed from the titles, which may be their source
    enricher.add_podcast_season_episode(season_namer(cfg.section("seasons")),
                                        _episode_number_getter(cfg))

    if titles.get("remove_episode_numbers"):
        if not title_rules.episode_number_re:
            raise ConfigError(f"{cfg.config_path}: remove_episode_numbers needs "
                              f"[titles] episode_number_pattern")
        enricher.remove_episode_numbers_from_titles(title_rules.episode_number_re.pattern)

    enricher.add_channel_persons(_load_hosts(cfg))

    if cfg.guid:
        enricher.add_guid(cfg.guid)

    # Guests from episode titles plus extra_episodes from known_guests.json
    known_guests = _load_known_guests(cfg)
    if titles.get("guest_pattern") or known_guests:
        enricher.auto_detect_guests_from_titles(title_rules=title_rules, known_guests=known_guests)

    funding = cfg.section("funding")
    if funding:
        enricher.add_funding(url=funding["url"], message=funding.get("message", "Support the show"))

    if podcast.get("medium"):
        enricher.add_medium(podcast["medium"])

    frequency = cfg.section("update_frequency")
    if frequency:
        enricher.add_update_frequency(
            complete=frequency.get("complete", False),
            frequency=frequency.get("frequency"),
            dtstart=frequency.get("dtstart"),
            rrule=frequency.get("rrule"),
        )

    podroll = cfg.list_section("podroll")
    if podroll:
        enricher.add_podroll([
            {"url": p["url"], **({"title": p["title"]} if "title" in p else {}),
             **({"feedGuid": p["feed_guid"]} if "feed_guid" in p else {})}
            for p in podroll
        ])

    for social in cfg.list_section("social_interact"):
        enricher.add_social_interact(
            protocol=social["protocol"],
            uri=social["uri"],
            account_id=social.get("account_id"),
            account_url=social.get("account_url"),
            priority=social.get("priority"),
        )

    # Per-episode Bluesky post (comment thread), matched via the article link
    article_domain = podcast.get("episode_article_domain")
    bluesky = cfg.section("bluesky")
    if bluesky.get("handle") and article_domain:
        enricher.add_bluesky_episode_social_interact(
            handle=bluesky["handle"],
            article_domain=article_domain,
            timezone=cfg.timezone,
        )

    # Drop redundant description-like fields. Empirical testing showed no
    # client relies exclusively on itunes:summary or content:encoded — all
    # tested clients either use <description> or fall back to it.
    if publish.get("remove_itunes_summary"):
        enricher.remove_itunes_summary()
    if publish.get("remove_content_encoded"):
        enricher.remove_content_encoded()

    footer = cfg.section("description_footer")
    if footer:
        footer_funding = None
        if funding and footer.get("funding_text"):
            footer_funding = {
                "name": funding.get("name", "funding"),
                "url": funding["url"],
                "text": footer["funding_text"],
            }
        texts = {param: footer[key] for key, param in [
            ("article_prefix", "episode_article_prefix"),
            ("article_text", "episode_article_text"),
            ("discussion_text", "discussion_text"),
            ("follow_text", "follow_text"),
            ("and_word", "and_word"),
        ] if key in footer}
        enricher.add_description_footer(
            episode_article_domain=article_domain,
            funding=footer_funding,
            social_links=footer.get("social_links", []),
            **texts,
        )

    if publish.get("op3"):
        enricher.add_op3_prefix()

    transcripts = cfg.section("transcripts")
    if transcripts.get("language"):
        enricher.add_language_to_transcripts(
            default_language=transcripts["language"],
            overrides=transcripts.get("language_overrides", {}),
        )
    if transcripts.get("version_podbean_urls"):
        enricher.add_transcript_versions()

    # Host chapter JSON files and rewrite podcast:chapters URLs to self-hosted.
    # psc:chapters is NOT added here — it's Spotify-specific and added by the
    # spotify variant, so the main feed stays clean.
    chapters = cfg.section("chapters")
    if chapters:
        apple_id = podcast.get("apple_podcast_id") if chapters.get("apple_links") else None
        enricher.convert_json_chapters_to_psc(
            include_psc_tags=False,
            apple_podcast_id=apple_id,
            apple_country=podcast.get("apple_country", "us"),
            **chapter_options(cfg),
        )

    return finish_feed(
        enricher, cfg,
        feed_file=cfg.feed_file,
        generator=publish.get("generator", "podcast-feed-updater v1.0"),
        shift_hours=publish.get("shift_latest_pubdate_hours"),
    )
