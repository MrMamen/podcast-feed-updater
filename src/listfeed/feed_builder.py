"""
Build a Podcasting 2.0 RSS feed from structured Podchaser list sections.

Unlike the cd SPILL enricher (which mutates an existing Podbean feed), this
generates a feed from scratch and aggregates episodes from many different
podcasts into one feed. Each list section becomes a named ``<podcast:season>``
(with an ``<itunes:season>`` mirror for clients that only understand iTunes).
Enclosure URLs are taken verbatim from Podchaser's ``audioUrl`` so any
source-side op3 prefix (e.g. cd SPILL's) is preserved and none is added.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Dict, List, Optional
from urllib.parse import urlsplit

from lxml import etree

# Norwegian month names, for parsing the event date out of a section heading
# like "TILTcast 5.0 (lørdag 30. mai 2026)".
_NO_MONTHS = {
    "januar": 1, "februar": 2, "mars": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11,
    "desember": 12,
}
_HEADING_DATE_RE = re.compile(r"(\d{1,2})\.?\s+([a-zæøå]+)\s+(\d{4})", re.IGNORECASE)

ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
PODCAST = "https://podcastindex.org/namespace/1.0"
ATOM = "http://www.w3.org/2005/Atom"
NSMAP = {"itunes": ITUNES, "podcast": PODCAST, "atom": ATOM}

_AUDIO_TYPES = {
    "mp3": "audio/mpeg",
    "m4a": "audio/x-m4a",
    "mp4": "audio/mp4",
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
    "opus": "audio/opus",
    "wav": "audio/wav",
    "aac": "audio/aac",
}


def _q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def _text(parent: etree._Element, tag: str, value) -> Optional[etree._Element]:
    """Append a child element with text, or do nothing when value is falsy."""
    if value is None or value == "":
        return None
    el = etree.SubElement(parent, tag)
    el.text = str(value)
    return el


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _rfc2822(value: Optional[str]) -> Optional[str]:
    dt = _parse_dt(value)
    return format_datetime(dt) if dt else None


def _parse_heading_date(heading: Optional[str]) -> Optional[datetime]:
    """Extract an event date (DD. <norwegian month> YYYY) from a section heading."""
    if not heading:
        return None
    m = _HEADING_DATE_RE.search(heading)
    if not m:
        return None
    day, month_name, year = m.group(1), m.group(2).lower(), m.group(3)
    month = _NO_MONTHS.get(month_name)
    if not month:
        return None
    try:
        return datetime(int(year), month, int(day), tzinfo=timezone.utc)
    except ValueError:
        return None


def assign_running_order_pubdates(sections: List[Dict], *, offset_minutes: int = 60,
                                  base_hour: int = 12) -> List[Dict]:
    """
    Assign synthetic pubDates so podcast apps (which sort by pubDate) display
    episodes in the curated running order rather than original publish order.

    Each section is anchored to its event date, derived purely from the list:
      1. the date in the section heading, else
      2. the earliest episode airDate in the section, else
      3. the previous section's anchor + 1 day.
    Episodes are then spaced ``offset_minutes`` apart by their position within
    the section (1 hour by default — episodes typically run longer than a few
    minutes), starting at ``base_hour``. Mutates each episode dict in place
    (sets ``pubDateOverride``) so the same episode gets an identical pubDate in
    every feed it appears in. Returns per-section info for logging.
    """
    log: List[Dict] = []
    prev_anchor: Optional[datetime] = None

    for section in sections:
        heading = section.get("heading")
        episodes = section.get("episodes", [])

        anchor = _parse_heading_date(heading)
        source = "heading date"
        if anchor is None:
            air_dts = [d for d in (_parse_dt(e.get("airDate")) for e in episodes) if d]
            if air_dts:
                anchor, source = min(air_dts), "earliest airDate"
        if anchor is None:
            if prev_anchor is not None:
                anchor, source = prev_anchor + timedelta(days=1), "previous section +1d"
            else:
                anchor, source = datetime(2000, 1, 1, tzinfo=timezone.utc), "fallback epoch"

        anchor = anchor.replace(hour=base_hour, minute=0, second=0, microsecond=0)
        prev_anchor = anchor

        for idx, ep in enumerate(episodes):
            ep["pubDateOverride"] = anchor + timedelta(minutes=offset_minutes * idx)

        log.append({"heading": heading, "anchor": anchor,
                    "source": source, "count": len(episodes)})
    return log


def _duration(seconds) -> Optional[str]:
    if not seconds:
        return None
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _audio_type(url: str) -> str:
    ext = urlsplit(url).path.rsplit(".", 1)[-1].lower()
    return _AUDIO_TYPES.get(ext, "audio/mpeg")


def _build_item(channel: etree._Element, ep: Dict, season_no: int,
                season_name: Optional[str], ep_no: int,
                channel_image: Optional[str]) -> None:
    item = etree.SubElement(channel, "item")
    _text(item, "title", ep.get("title"))

    audio = ep.get("audioUrl")
    if audio:
        enc = etree.SubElement(item, "enclosure")
        enc.set("url", audio)  # verbatim — preserves source op3 prefix if present
        enc.set("type", _audio_type(audio))
        enc.set("length", str(ep.get("fileSize") or 0))

    guid = etree.SubElement(item, "guid")
    guid.set("isPermaLink", "false")
    guid.text = ep.get("guid") or f"podchaser-episode-{ep.get('id')}"

    override = ep.get("pubDateOverride")
    _text(item, "pubDate",
          format_datetime(override) if override else _rfc2822(ep.get("airDate")))
    _text(item, "link", ep.get("webUrl") or ep.get("url"))
    _text(item, "description", ep.get("htmlDescription"))

    # Surface which podcast the episode actually comes from (cross-podcast list).
    podcast = ep.get("podcast") or {}
    _text(item, _q(ITUNES, "author"), podcast.get("title"))

    ep_image = ep.get("imageUrl") or podcast.get("imageUrl") or channel_image
    if ep_image:
        etree.SubElement(item, _q(ITUNES, "image")).set("href", ep_image)

    _text(item, _q(ITUNES, "duration"), _duration(ep.get("length")))
    _text(item, _q(ITUNES, "explicit"), "true" if ep.get("explicit") else "false")
    # Normalize to "full": bonus/trailer status was relative to the source
    # podcast; in this curated list every entry is a first-class episode.
    _text(item, _q(ITUNES, "episodeType"), "full")

    season = etree.SubElement(item, _q(PODCAST, "season"))
    if season_name:
        season.set("name", season_name)
    season.text = str(season_no)
    _text(item, _q(ITUNES, "season"), str(season_no))
    _text(item, _q(ITUNES, "episode"), str(ep_no))


def build_feed(*, title: str, description: Optional[str], language: str,
               author: str, category: Dict, explicit: bool,
               image_url: Optional[str], self_url: str, link: str,
               generator: str, last_build_raw: Optional[str],
               sections: List[Dict], output_file: str,
               podcast_type: str = "episodic") -> int:
    """
    Build one RSS feed and write it to ``output_file``.

    Each entry in ``sections`` (``{"heading", "episodes"}``) becomes a season,
    numbered in order. ``explicit`` is the configured baseline; the channel is
    additionally marked explicit if any episode in the feed is. ``podcast_type``
    is the iTunes show type ("episodic" or "serial"). Returns the episode count.
    """
    # Channel explicit must reflect the actual content (Apple requirement).
    any_explicit = any(ep.get("explicit")
                       for section in sections
                       for ep in section.get("episodes", []))

    rss = etree.Element("rss", nsmap=NSMAP)
    rss.set("version", "2.0")
    channel = etree.SubElement(rss, "channel")

    _text(channel, "title", title)
    _text(channel, "link", link)
    _text(channel, "language", language)
    _text(channel, "description", description or title)
    _text(channel, _q(ITUNES, "author"), author)
    _text(channel, _q(ITUNES, "type"), podcast_type)
    _text(channel, _q(ITUNES, "explicit"), "true" if (explicit or any_explicit) else "false")

    if image_url:
        etree.SubElement(channel, _q(ITUNES, "image")).set("href", image_url)
        rss_image = etree.SubElement(channel, "image")
        _text(rss_image, "url", image_url)
        _text(rss_image, "title", title)
        _text(rss_image, "link", link)

    cat = etree.SubElement(channel, _q(ITUNES, "category"))
    cat.set("text", category["text"])
    if category.get("sub"):
        etree.SubElement(cat, _q(ITUNES, "category")).set("text", category["sub"])

    _text(channel, _q(PODCAST, "medium"), "podcast")
    _text(channel, _q(PODCAST, "guid"), str(uuid.uuid5(uuid.NAMESPACE_URL, self_url)))

    atom_link = etree.SubElement(channel, _q(ATOM, "link"))
    atom_link.set("href", self_url)
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    _text(channel, "lastBuildDate", _rfc2822(last_build_raw))
    _text(channel, "generator", generator)

    episode_count = 0
    for season_no, section in enumerate(sections, start=1):
        season_name = section.get("heading")
        for ep_no, ep in enumerate(section.get("episodes", []), start=1):
            _build_item(channel, ep, season_no, season_name, ep_no, image_url)
            episode_count += 1

    etree.ElementTree(rss).write(
        output_file, encoding="utf-8", xml_declaration=True, pretty_print=True
    )
    print(f"  ✓ {output_file}  ({episode_count} episodes)")
    return episode_count
