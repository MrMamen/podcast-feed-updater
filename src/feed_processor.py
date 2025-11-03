"""
Podcast Feed Processor
Fetches, filters, and enriches podcast RSS feeds.
"""

import re
from typing import List, Dict, Optional, Callable
import feedparser
from feedgen.feed import FeedGenerator
import requests


class PodcastFeedProcessor:
    """Main class for processing podcast feeds."""

    def __init__(self, source_feed_url: str):
        """
        Initialize the processor with a source feed URL.

        Args:
            source_feed_url: URL of the podcast RSS feed to process
        """
        self.source_url = source_feed_url
        self.parsed_feed = None
        self.filtered_entries = []

    def fetch_feed(self) -> None:
        """Fetch and parse the source feed."""
        print(f"Fetching feed from: {self.source_url}")
        self.parsed_feed = feedparser.parse(self.source_url)

        if self.parsed_feed.bozo:
            print(f"Warning: Feed parsing encountered issues: {self.parsed_feed.bozo_exception}")

        print(f"Found {len(self.parsed_feed.entries)} episodes in feed")

    def filter_by_title_pattern(self, pattern: str, keep_matching: bool = True) -> 'PodcastFeedProcessor':
        """
        Filter episodes based on title pattern.

        Args:
            pattern: Regex pattern to match against episode titles
            keep_matching: If True, keep matching episodes. If False, exclude them.

        Returns:
            Self for method chaining
        """
        if not self.parsed_feed:
            raise ValueError("Must fetch feed before filtering")

        regex = re.compile(pattern, re.IGNORECASE)

        for entry in self.parsed_feed.entries:
            title = entry.get('title', '')
            matches = bool(regex.search(title))

            if (keep_matching and matches) or (not keep_matching and not matches):
                self.filtered_entries.append(entry)

        print(f"Filter '{pattern}' resulted in {len(self.filtered_entries)} episodes")
        return self

    def filter_by_custom_function(self, filter_func: Callable) -> 'PodcastFeedProcessor':
        """
        Filter episodes using a custom function.

        Args:
            filter_func: Function that takes an entry dict and returns True to keep it

        Returns:
            Self for method chaining
        """
        if not self.parsed_feed:
            raise ValueError("Must fetch feed before filtering")

        self.filtered_entries = [
            entry for entry in self.parsed_feed.entries
            if filter_func(entry)
        ]

        print(f"Custom filter resulted in {len(self.filtered_entries)} episodes")
        return self

    def enrich_with_persons(self, persons_mapping: Dict[str, List[Dict[str, str]]]) -> 'PodcastFeedProcessor':
        """
        Enrich episodes with Podcasting 2.0 person tags.

        Args:
            persons_mapping: Dict mapping episode IDs or patterns to person info.
                            Example: {"episode_guid": [{"name": "John Doe", "role": "host", "href": "..."}]}

        Returns:
            Self for method chaining
        """
        for entry in self.filtered_entries:
            # You can extend this to match by different criteria
            entry_id = entry.get('id', '')
            if entry_id in persons_mapping:
                entry['podcast_persons'] = persons_mapping[entry_id]

        return self

    def generate_feed(
        self,
        output_file: str,
        feed_title: Optional[str] = None,
        feed_description: Optional[str] = None,
        feed_link: Optional[str] = None,
    ) -> None:
        """
        Generate a new RSS feed from filtered entries.

        Args:
            output_file: Path to write the output feed
            feed_title: Override feed title
            feed_description: Override feed description
            feed_link: Override feed link
        """
        if not self.filtered_entries:
            print("Warning: No entries to generate feed from")
            return

        # Create feed generator
        fg = FeedGenerator()

        # Set feed metadata (use original or overrides)
        original_feed = self.parsed_feed.feed
        fg.title(feed_title or original_feed.get('title', 'Filtered Podcast Feed'))
        fg.description(feed_description or original_feed.get('description', 'Filtered podcast feed'))
        fg.link(href=feed_link or original_feed.get('link', ''))

        # Copy other metadata
        if 'language' in original_feed:
            fg.language(original_feed.language)
        if 'image' in original_feed:
            fg.image(original_feed.image.get('href', ''))

        # Add iTunes/Podcast namespace support
        fg.load_extension('podcast')

        # Add entries
        for entry in self.filtered_entries:
            fe = fg.add_entry()
            fe.id(entry.get('id', entry.get('link', '')))
            fe.title(entry.get('title', 'Untitled'))
            fe.description(entry.get('description', ''))

            if 'link' in entry:
                fe.link(href=entry.link)

            if 'published_parsed' in entry:
                from datetime import datetime, timezone
                # Create timezone-aware datetime (assume UTC if not specified)
                dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                fe.published(dt)

            # Add enclosure (audio file)
            if 'enclosures' in entry and entry.enclosures:
                enclosure = entry.enclosures[0]
                fe.enclosure(
                    url=enclosure.get('href', ''),
                    length=enclosure.get('length', '0'),
                    type=enclosure.get('type', 'audio/mpeg')
                )

            # Add podcast:person tags if enriched
            if 'podcast_persons' in entry:
                for person in entry['podcast_persons']:
                    # This requires feedgen to support podcast namespace
                    # We'll add custom XML elements
                    pass  # Will implement in next iteration

        # Write to file
        fg.rss_file(output_file, pretty=True)
        print(f"Generated feed written to: {output_file}")


def create_filtered_feed(
    source_url: str,
    output_file: str,
    title_pattern: Optional[str] = None,
    new_title: Optional[str] = None,
) -> None:
    """
    Convenience function to create a filtered feed.

    Args:
        source_url: Source feed URL
        output_file: Output file path
        title_pattern: Pattern to filter episode titles
        new_title: New feed title
    """
    processor = PodcastFeedProcessor(source_url)
    processor.fetch_feed()

    if title_pattern:
        processor.filter_by_title_pattern(title_pattern)
    else:
        # Keep all entries if no filter
        processor.filtered_entries = processor.parsed_feed.entries

    processor.generate_feed(output_file, feed_title=new_title)
