"""
Shared helpers for reasoning about a podcast's episodes: its title conventions
([titles] in podcast.toml) and season names ([seasons]).
"""

from __future__ import annotations

import re
import uuid
from typing import Callable, Dict, List, Optional, Union

EPISODE_NUMBER_SOURCES = ("itunes", "title")

# Namespace for podcast:guid, see https://podcasting2.org/docs/podcast-namespace/tags/guid
PODCAST_GUID_NAMESPACE = uuid.UUID("ead4c236-bf58-58c6-a2c6-a6b28d128cb6")


def podcast_guid(feed_url: str) -> str:
    """podcast:guid as Podcast Index derives it: uuid5 of the feed URL without scheme."""
    return str(uuid.uuid5(PODCAST_GUID_NAMESPACE, re.sub(r'^[a-z]+://', '', feed_url).rstrip('/')))


def is_bonus_episode(text: str) -> bool:
    """Return True if the title or note looks like a bonus episode."""
    if not text:
        return False
    lowered = text.lower()
    return "bonus" in lowered


class TitleRules:
    """
    How a podcast writes its episode titles, e.g. cd SPILL's
    ``"Game Name med Guest A og Guest B (#123)"``:

    - ``guest_pattern``: regex whose group 1 holds the guest name(s)
      (``med (.+?)(?:\\s*\\(|$)``). None: titles don't name guests.
    - ``guest_separator``: word(s) between several guests (``og``).
    - ``subject_separator``: text between what the episode is about and the
      guests (``" med "``), used to match chapters against other episodes.
    - ``episode_number_pattern``: regex for the episode number in the title,
      with the number as group 1 (``\\s*\\(#?(\\d+)\\)$`` for ``"(#123)"``).
    """

    def __init__(
        self,
        guest_pattern: Optional[str] = None,
        guest_separator: Union[str, List[str], None] = None,
        subject_separator: Optional[str] = None,
        episode_number_pattern: Optional[str] = None,
    ):
        self.guest_pattern = re.compile(guest_pattern, re.IGNORECASE) if guest_pattern else None
        separators = [guest_separator] if isinstance(guest_separator, str) else guest_separator or []
        self.guest_split = (
            re.compile(r'\s+(?:' + '|'.join(map(re.escape, separators)) + r')\s+', re.IGNORECASE)
            if separators else None
        )
        self.subject_separator = subject_separator
        self.episode_number_re = re.compile(episode_number_pattern) if episode_number_pattern else None

    @classmethod
    def from_config(cls, titles: Dict) -> 'TitleRules':
        """Build from the [titles] section of podcast.toml."""
        return cls(
            guest_pattern=titles.get("guest_pattern"),
            guest_separator=titles.get("guest_separator"),
            subject_separator=titles.get("subject_separator"),
            episode_number_pattern=titles.get("episode_number_pattern"),
        )

    def strip_episode_number(self, title: str) -> str:
        """The title without its episode number (``"Game (#123)"`` → ``"Game"``)."""
        if not self.episode_number_re:
            return title or ''
        return self.episode_number_re.sub('', title or '')

    def episode_number(self, title: str) -> Optional[str]:
        """The episode number in the title (group 1 of the pattern), or None."""
        match = self.episode_number_re.search(title or '') if self.episode_number_re else None
        return match.group(1) if match and match.groups() else None

    def extract_guests(self, title: str) -> List[str]:
        """
        Return the guest names in a title, e.g. ``["Guest A", "Guest B"]`` for
        ``"Game Name med Guest A og Guest B (#123)"``; [] when there are none.
        """
        if not title or not self.guest_pattern:
            return []

        match = self.guest_pattern.search(title)
        if not match:
            return []

        guest_blob = self.strip_episode_number(match.group(1).strip())

        parts = self.guest_split.split(guest_blob) if self.guest_split else [guest_blob]
        return [p.strip() for p in parts if p.strip()]

    def subject(self, title: str) -> str:
        """What the episode is about: ``"Rainbow Six med Jostein Hakestad"`` → ``"Rainbow Six"``."""
        title = title or ''
        if self.subject_separator:
            title = title.split(self.subject_separator)[0]
        return title.strip()


def season_namer(seasons: Dict) -> Optional[Callable[[int], str]]:
    """
    Function from season number to podcast:season name, from the [seasons]
    section of podcast.toml, or None when seasons have no names.

    naming = "half_year": two seasons a year starting in ``first_year``, named
        with ``half_year_names`` (["Vår", "Høst"] → S1 "Vår 2020", S2 "Høst 2020").
    naming = "format": ``name_format`` for every season ("Sesong {season}").
    Seasons ≤ 0 always use ``name_format``.
    """
    naming = seasons.get("naming")
    if not naming:
        return None
    name_format = seasons.get("name_format", "Season {season}")

    if naming == "format":
        return lambda season: name_format.format(season=season)

    if naming == "half_year":
        first_year = seasons["first_year"]
        first_half, second_half = seasons.get("half_year_names", ["Spring", "Fall"])

        def half_year_name(season: int) -> str:
            if season <= 0:
                return name_format.format(season=season)
            year = first_year + (season - 1) // 2
            return f"{first_half if season % 2 == 1 else second_half} {year}"

        return half_year_name

    raise ValueError(f"Unknown [seasons] naming: {naming!r} (use 'half_year' or 'format')")
