"""
Feed Enricher - Add Podcasting 2.0 tags to existing feeds.
Preserves all original content while adding new metadata.

The methods are grouped by topic in mixins (persons, episode_numbers, channel,
social, descriptions, transcripts, chapters); this class combines them. All
methods return self, so they can be chained.
"""

from typing import Self

from src.enrichment.channel import ChannelMixin
from src.enrichment.chapters import ChaptersMixin
from src.enrichment.descriptions import DescriptionsMixin
from src.enrichment.episode_numbers import EpisodeNumbersMixin
from src.enrichment.persons import PersonsMixin
from src.enrichment.social import SocialMixin
from src.enrichment.transcripts import TranscriptsMixin


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

    def validate_no_conflicts(self) -> Self:
        """
        Validate that the source feed doesn't already contain Podcasting 2.0 tags
        that this enricher will add. This prevents silent conflicts when the
        original feed starts supporting these tags.

        Raises:
            ValueError: If any conflicting tags are found

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        PODCAST_NS = 'https://podcastindex.org/namespace/1.0'

        # Tags we check at channel level
        channel_tags_to_check = [
            'guid', 'funding', 'medium', 'updateFrequency',
            'podroll', 'socialInteract', 'person'
        ]

        # Tags we check at item level
        item_tags_to_check = ['season', 'episode', 'person', 'socialInteract']

        conflicts = []

        # Check channel level
        for tag in channel_tags_to_check:
            found = self.channel.findall(f'{{{PODCAST_NS}}}{tag}')
            if found:
                conflicts.append(f"podcast:{tag} (found {len(found)} at channel level)")

        # Check item level
        items = self.channel.findall('item')
        item_conflicts = {}
        for tag in item_tags_to_check:
            for item in items:
                found = item.findall(f'{{{PODCAST_NS}}}{tag}')
                if found:
                    if tag not in item_conflicts:
                        item_conflicts[tag] = 0
                    item_conflicts[tag] += len(found)

        for tag, count in item_conflicts.items():
            conflicts.append(f"podcast:{tag} (found {count} across episodes)")

        if conflicts:
            error_msg = (
                "\n" + "="*60 + "\n"
                "CONFLICT DETECTED: Source feed already contains Podcasting 2.0 tags!\n"
                + "="*60 + "\n\n"
                "The original feed now has support for tags that this enricher adds.\n"
                "Please update the enrichment script to handle these tags.\n\n"
                "Conflicting tags found:\n"
            )
            for conflict in conflicts:
                error_msg += f"  ❌ {conflict}\n"
            error_msg += (
                "\nThis is intentional to prevent silent conflicts.\n"
                "Update the podcast's podcast.toml or the pipeline to either:\n"
                "  1. Stop adding these tags (remove the config section)\n"
                "  2. Modify the enricher to handle existing tags\n"
                "  3. Add explicit override logic if needed\n"
            )
            raise ValueError(error_msg)

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
