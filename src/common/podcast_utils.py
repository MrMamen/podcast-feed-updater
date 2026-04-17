"""Shared helpers for reasoning about cd SPILL episodes."""

from __future__ import annotations

import re
from typing import List

TITLE_GUEST_PATTERN = re.compile(r'med (.+?)(?:\s*\(|$)', re.IGNORECASE)
_EPISODE_SUFFIX_RE = re.compile(r'\s*\(#?\d+\)$')
_AND_SPLIT_RE = re.compile(r'\s+og\s+', re.IGNORECASE)


def is_bonus_episode(text: str) -> bool:
    """Return True if the title or note looks like a bonus episode."""
    if not text:
        return False
    lowered = text.lower()
    return "bonus" in lowered


def extract_guests_from_title(title: str) -> List[str]:
    """
    Return a list of guest names parsed from a title like
    ``"Game Name med Guest A og Guest B (#123)"``.

    An empty list is returned when the "med ..." pattern is missing.
    """
    if not title:
        return []

    match = TITLE_GUEST_PATTERN.search(title)
    if not match:
        return []

    guest_blob = match.group(1).strip()
    guest_blob = _EPISODE_SUFFIX_RE.sub('', guest_blob)

    if _AND_SPLIT_RE.search(guest_blob):
        parts = _AND_SPLIT_RE.split(guest_blob)
    else:
        parts = [guest_blob]

    return [p.strip() for p in parts if p.strip()]
