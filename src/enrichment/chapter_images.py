"""
Pick an image for chapters that don't have one.

The order, first match wins:

1. The first chapter (startTime 0) gets the episode's cover.
2. ``image_rules`` from [chapters] in podcast.toml: keywords in the chapter
   title → an image (the episode's or a neighbour's cover, the podcast logo or
   a file from the chapter images directory).
3. A chapter linking to Steam, GOG or Wikipedia gets the game's cover.
4. The chapter title matches what another episode is about ("Doom II" →
   the Doom episode): exact, as suffix, as prefix, or the other way round.
5. ``cross_references`` from podcast.toml: phrases followed by another
   episode's name ("Ligner på Doom").
6. Fuzzy word overlap with another episode's subject.

Steps 4 and 6 suit podcasts where each episode is about one thing (a game),
and are only on with ``match_other_episodes``.

Titles are compared case-insensitively, with curly apostrophes made straight.
"""

from __future__ import annotations

import string
from typing import Callable, Dict, List, Optional

# Images an image rule can name besides a file in the images directory
EPISODE_COVER = "episode_cover"
PREVIOUS_COVER = "previous_cover"
NEXT_COVER = "next_cover"
PODCAST_LOGO = "podcast_logo"
SPECIAL_IMAGES = {EPISODE_COVER, PREVIOUS_COVER, NEXT_COVER, PODCAST_LOGO}

IMAGE_RULE_KEYS = {"image", "starts_with", "contains", "equals"}
CROSS_REFERENCE_KEYS = {"starts_with", "contains", "match", "unless_contains"}
CROSS_REFERENCE_MATCHES = {"exact", "contains", "words"}

# Returned by a cross-reference rule to stop matching this chapter altogether
_STOP = object()


def normalize_title(title: str) -> str:
    """Lowercase with straight apostrophes, so chapter files and feed titles compare equal."""
    return title.replace('\u2019', "'").lower()


def _normalize_words(text: str) -> set:
    """Remove punctuation and split into words for fuzzy matching."""
    return set(text.translate(str.maketrans('', '', string.punctuation)).lower().split())


# Whole-word prefix/suffix checks, so "doom" doesn't match "doomsday machine"
# and "spillåret 1993" doesn't match "eventyrspillåret 1993"
def _starts_with_word(text: str, prefix: str) -> bool:
    return text.startswith(prefix) and (
        len(text) == len(prefix) or not text[len(prefix)].isalnum()
    )


def _ends_with_word(text: str, suffix: str) -> bool:
    start = len(text) - len(suffix)
    return text.endswith(suffix) and (start == 0 or not text[start - 1].isalnum())


def _lowered(values) -> List[str]:
    return [normalize_title(v) for v in ([values] if isinstance(values, str) else values or [])]


class _ImageRule:
    def __init__(self, rule: Dict):
        unknown = set(rule) - IMAGE_RULE_KEYS
        if unknown or "image" not in rule:
            raise ValueError(f"Invalid [[chapters.image_rules]] entry {rule}: needs 'image' and "
                             f"any of starts_with/contains/equals (unknown: {sorted(unknown)})")
        self.image = rule["image"]
        self.starts_with = _lowered(rule.get("starts_with"))
        self.contains = _lowered(rule.get("contains"))
        self.equals = _lowered(rule.get("equals"))

    def matches(self, title: str) -> bool:
        return (any(title.startswith(p) for p in self.starts_with)
                or any(p in title for p in self.contains)
                or title in self.equals)


class _CrossReference:
    def __init__(self, rule: Dict):
        unknown = set(rule) - CROSS_REFERENCE_KEYS
        match = rule.get("match", "exact")
        if unknown or match not in CROSS_REFERENCE_MATCHES:
            raise ValueError(f"Invalid [[chapters.cross_references]] entry {rule}: match must be one of "
                             f"{sorted(CROSS_REFERENCE_MATCHES)} (unknown keys: {sorted(unknown)})")
        self.starts_with = _lowered(rule.get("starts_with"))
        self.contains = _lowered(rule.get("contains"))
        self.match = match
        self.unless_contains = _lowered(rule.get("unless_contains"))

    def referenced_names(self, title: str) -> List[str]:
        """The text after each phrase found in the title: the referenced episode's name."""
        if any(x in title for x in self.unless_contains):
            return []
        names = [title[len(p):].strip() for p in self.starts_with if title.startswith(p)]
        names += [title.split(p, 1)[1].strip() for p in self.contains if p in title]
        return names


class ChapterImageMatcher:
    """
    Chooses chapter images for one feed.

    Args:
        subject_covers: What each episode is about (normalized, see
            ``normalize_title``) → that episode's cover URL
        image_rules: ``[[chapters.image_rules]]`` from podcast.toml
        cross_references: ``[[chapters.cross_references]]`` from podcast.toml
        images_base_url: Public URL of the chapter images directory, for rules
            whose image is a file name
        link_cover: Cover URL for a chapter link (Steam/GOG/Wikipedia), or None
        match_other_episodes: Match chapter titles against other episodes'
            subjects (steps 4 and 6)
    """

    def __init__(
        self,
        subject_covers: Dict[str, str],
        image_rules: Optional[List[Dict]] = None,
        cross_references: Optional[List[Dict]] = None,
        images_base_url: Optional[str] = None,
        link_cover: Optional[Callable[[str], Optional[str]]] = None,
        match_other_episodes: bool = False,
    ):
        self.subject_covers = subject_covers
        self.match_other_episodes = match_other_episodes
        self.image_rules = [_ImageRule(r) for r in image_rules or []]
        self.cross_references = [_CrossReference(r) for r in cross_references or []]
        self.images_base_url = images_base_url
        self.link_cover = link_cover

    def _rule_image(self, image: str, covers: Dict[str, Optional[str]]) -> Optional[str]:
        if image in SPECIAL_IMAGES:
            return covers.get(image)
        if image.startswith(("http://", "https://")):
            return image
        return f"{self.images_base_url}/{image}" if self.images_base_url else None

    def image_for(self, chapter: Dict, covers: Dict[str, Optional[str]]) -> Optional[str]:
        """
        Image for ``chapter``, or None.

        ``covers`` holds this episode's context: ``episode_cover``,
        ``previous_cover``, ``next_cover`` and ``podcast_logo`` (any may be None).
        """
        title = normalize_title(chapter.get('title', '').strip())

        # 1. First chapter: always the episode cover (regardless of title)
        if chapter.get('startTime', 0) == 0 and covers.get(EPISODE_COVER):
            return covers[EPISODE_COVER]

        # 2. Podcast-specific keyword rules; a rule whose image is missing
        #    (e.g. no previous episode) lets the next rule try
        for rule in self.image_rules:
            if rule.matches(title):
                image = self._rule_image(rule.image, covers)
                if image:
                    return image

        # 3. Chapter links to Steam, GOG or Wikipedia: use the game's cover.
        #    Takes precedence over episode matching, so "Syndicate Wars" linked
        #    to GOG doesn't get the Syndicate episode cover.
        url = chapter.get('url')
        if url and self.link_cover:
            image = self.link_cover(url)
            if image:
                return image

        # 4. The chapter title refers to another episode
        if self.match_other_episodes:
            image = self._match_subject(title)
            if image:
                return image

        # 5. Podcast-specific phrases introducing another episode's name
        for reference in self.cross_references:
            image = self._match_cross_reference(reference, title)
            if image is _STOP:
                return None
            if image:
                return image

        # 6. Last resort
        return self._match_fuzzy(title) if self.match_other_episodes else None

    def _match_subject(self, title: str) -> Optional[str]:
        covers = self.subject_covers

        # Exact: "Home Alone" chapter in the OutRun episode gets the Home Alone cover
        if title in covers:
            return covers[title]

        # Suffix: "Historien i Duke Nukem" → Duke Nukem episode. Also normalize a
        # "the " prefix ("Oppsummering av Secret of Monkey Island" → "The Secret of
        # Monkey Island"), but only if the result has several words (to avoid
        # "the games" → "games" false matches)
        for name, cover in covers.items():
            if len(name) <= 3:
                continue
            normalized = name
            if normalized.startswith("the "):
                without_the = normalized[4:]
                if ' ' in without_the:
                    normalized = without_the
            if _ends_with_word(title, normalized):
                return cover

        # Prefix, longest match wins: "Doom II" → "Doom", "Transport Tycoon Deluxe" →
        # "Transport Tycoon", and "Legend of Kyrandia" matches "the legend of kyrandia:
        # hand of fate" rather than just "legend". "the " is stripped from the chapter
        # only when the episode name has it too (so "The Legend of Zelda" doesn't
        # match "Legend")
        best, best_length = None, 0
        for name, cover in covers.items():
            if len(name) <= 3:
                continue
            normalized, chapter_normalized = name, title
            if normalized.startswith("the "):
                normalized = normalized[4:]
                if chapter_normalized.startswith("the "):
                    chapter_normalized = chapter_normalized[4:]
            if _starts_with_word(chapter_normalized, normalized) and len(normalized) > best_length:
                best, best_length = cover, len(normalized)
        if best:
            return best

        # Reverse prefix, longest episode name wins: "Backpacker" → "Backpacker 2"
        best, best_length = None, 0
        for name, cover in covers.items():
            if len(title) > 3 and _starts_with_word(name, title) and len(name) > best_length:
                best, best_length = cover, len(name)
        return best

    def _match_cross_reference(self, reference: _CrossReference, title: str):
        for name in reference.referenced_names(title):
            if reference.match == "exact":
                if name in self.subject_covers:
                    return self.subject_covers[name]

            elif reference.match == "contains":
                # "Mer Warcraft II" → contains "warcraft"
                for episode_name, cover in self.subject_covers.items():
                    if len(episode_name) > 3 and episode_name in name:
                        return cover

            elif reference.match == "words":
                # Very short names would match too much ("Kommentarer fra I" →
                # "I Have No Mouth..."), so give up on this chapter
                if len(name) <= 3:
                    return _STOP
                # Word overlap, so "Kommentarer fra Freddi Fisk" matches "freddi
                # fisk og humongous entertainment": at least 2 words in common, or
                # all of the name's words
                words = _normalize_words(name)
                best, best_score = None, 0
                for episode_name, cover in self.subject_covers.items():
                    if len(episode_name) <= 3:
                        continue
                    score = len(words & _normalize_words(episode_name))
                    if (score >= 2 or (words and score == len(words))) and score > best_score:
                        best, best_score = cover, score
                if best:
                    return best
        return None

    def _match_fuzzy(self, title: str) -> Optional[str]:
        # Word overlap for multi-word titles: "Heroes of Might and Magic" →
        # "Heroes of Might & Magic". Only for at least 3 words, and at least 80%
        # of the chapter's words must be in the episode's subject
        words = _normalize_words(title)
        if len(words) < 3:
            return None
        best, best_score = None, 0
        for name, cover in self.subject_covers.items():
            if len(name) <= 3:
                continue
            score = len(words & _normalize_words(name))
            if score >= len(words) * 0.8 and score > best_score:
                best, best_score = cover, score
        return best
