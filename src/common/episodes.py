"""Helpers for iterating over and locating episodes in the cd SPILL feed XML."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Optional

from lxml import etree

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"


@dataclass
class Episode:
    guid: str
    title: str
    link: str
    episode_num: str  # itunes:episode as text, '' if missing
    duration: str  # itunes:duration raw text, '' if missing
    episode_type: str  # itunes:episodeType, 'full' if missing


def _text(item, tag: str) -> str:
    elem = item.find(tag)
    return elem.text if elem is not None and elem.text else ""


def iter_episodes(feed_xml: str) -> Iterator[Episode]:
    root = etree.fromstring(feed_xml.encode("utf-8"))
    for item in root.findall(".//item"):
        yield Episode(
            guid=_text(item, "guid"),
            title=_text(item, "title"),
            link=_text(item, "link"),
            episode_num=_text(item, f"{{{ITUNES_NS}}}episode"),
            duration=_text(item, f"{{{ITUNES_NS}}}duration"),
            episode_type=_text(item, f"{{{ITUNES_NS}}}episodeType") or "full",
        )


def find_episode(feed_xml: str, search_term: str) -> Optional[Episode]:
    """
    Find an episode by number (``#106`` / ``106``), GUID substring, or
    case-insensitive title substring — in that order of preference.
    """
    number = None
    if search_term.startswith("#"):
        number = search_term[1:]
    elif search_term.isdigit():
        number = search_term

    episodes = list(iter_episodes(feed_xml))
    if number:
        for ep in episodes:
            if ep.episode_num == number:
                return ep
    for ep in episodes:
        if search_term in ep.guid:
            return ep
    lowered = search_term.lower()
    for ep in episodes:
        if lowered in ep.title.lower():
            return ep
    return None


def parse_duration(raw: str) -> Optional[int]:
    """Parse ``H:MM:SS``, ``M:SS`` or plain seconds into an int; None if invalid."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        if ":" in raw:
            seconds = 0
            for part in raw.split(":"):
                seconds = seconds * 60 + int(part)
            return seconds
        return int(raw)
    except ValueError:
        return None
