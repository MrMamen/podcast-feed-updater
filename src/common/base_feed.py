"""
Base class for feed operations using lxml.
Provides common functionality for fetching and writing RSS feeds.
"""

import requests
from lxml import etree
from typing import Optional


class BaseFeed:
    """Base class for all feed operations."""

    def __init__(self, source_url: str):
        """
        Initialize feed processor.

        Args:
            source_url: URL of RSS feed to process
        """
        self.source_url = source_url
        self.root: Optional[etree._Element] = None
        self.channel: Optional[etree._Element] = None

    def fetch_feed(self) -> None:
        """Fetch and parse RSS feed from source URL."""
        print(f"Fetching feed: {self.source_url}")
        response = requests.get(self.source_url, timeout=30)
        response.raise_for_status()

        self.root = etree.fromstring(response.content)
        self.channel = self.root.find('channel')

        if self.channel is None:
            raise ValueError("No channel found in feed")

        items = self.channel.findall('item')
        print(f"Found {len(items)} episodes")

    def write_feed(self, output_file: str) -> None:
        """
        Write feed to file.

        Args:
            output_file: Output file path
        """
        if self.root is None:
            raise ValueError("No feed loaded")

        tree = etree.ElementTree(self.root)
        tree.write(
            output_file,
            encoding='utf-8',
            xml_declaration=True,
            pretty_print=True
        )

        print(f"✓ Feed written to: {output_file}")

    def _ensure_podcast_namespace(self) -> None:
        """Ensure podcast namespace is registered in root element."""
        nsmap = self.root.nsmap.copy()
        if 'podcast' not in nsmap:
            nsmap['podcast'] = 'https://podcastindex.org/namespace/1.0'
            # Recreate root with new nsmap
            new_root = etree.Element(self.root.tag, attrib=self.root.attrib, nsmap=nsmap)
            for child in self.root:
                new_root.append(child)
            self.root = new_root
            self.channel = self.root.find('channel')
