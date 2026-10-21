"""
Feed Enricher - Add Podcasting 2.0 tags to existing feeds.
Preserves all original content while adding new metadata.

The methods are grouped by topic in mixins (persons, episode_numbers, channel,
social, descriptions, transcripts, chapters); this class combines them. All
methods return self, so they can be chained.
"""

from typing import Dict, Self

from src.common.namespaces import PODCAST
from src.enrichment.channel import ChannelMixin
from src.enrichment.chapters import ChaptersMixin
from src.enrichment.descriptions import DescriptionsMixin
from src.enrichment.episode_numbers import EpisodeNumbersMixin
from src.enrichment.persons import PersonsMixin
from src.enrichment.social import SocialMixin
from src.enrichment.transcripts import TranscriptsMixin


class FeedConflictError(Exception):
    """The source feed already has tags the configuration would add."""


class FeedEnricher(
    PersonsMixin,
    EpisodeNumbersMixin,
    ChannelMixin,
    SocialMixin,
    DescriptionsMixin,
    TranscriptsMixin,
    ChaptersMixin,
):
    """Enrich podcast feeds with Podcasting 2.0 tags."""

    def validate_no_conflicts(self, channel_tags: Dict[str, str], item_tags: Dict[str, str]) -> Self:
        """
        Fail if the source feed already has Podcasting 2.0 tags that the
        configured steps would add, so they aren't added twice without anyone
        noticing (e.g. when the host starts supporting a tag).

        Args:
            channel_tags, item_tags: podcast: tag name → the setting that adds it,
                for the error message (e.g. {"guid": "[podcast] guid"})

        Raises:
            FeedConflictError: listing the tags and settings
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        conflicts = []
        for tag, setting in channel_tags.items():
            found = len(self.channel.findall(f'{PODCAST}{tag}'))
            if found:
                conflicts.append(f"podcast:{tag} ({found} at channel level), added by {setting}")
        for tag, setting in item_tags.items():
            found = sum(len(item.findall(f'{PODCAST}{tag}')) for item in self.channel.findall('item'))
            if found:
                conflicts.append(f"podcast:{tag} ({found} in episodes), added by {setting}")

        if conflicts:
            raise FeedConflictError(
                "The source feed already has tags that the configuration adds:\n"
                + "".join(f"  ❌ {c}\n" for c in conflicts)
                + "Remove these settings to keep the source feed's own tags."
            )

        print("✓ Validation passed: No conflicting Podcasting 2.0 tags found")
        return self

    def write_feed(self, output_file: str) -> None:
        """
        Write enriched feed to file.

        Args:
            output_file: Output file path
        """
        super().write_feed(output_file)
        print(f"✓ Enriched feed written to: {output_file}")
