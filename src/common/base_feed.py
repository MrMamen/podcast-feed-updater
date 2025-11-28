"""
Base class for feed operations using lxml.
Provides common functionality for fetching and writing RSS feeds.
"""

import requests
from lxml import etree
from typing import Optional
import os


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
        self.source_latest_pubdate: Optional[str] = None
        self.source_latest_link: Optional[str] = None

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

        # Get latest episode pubDate and link (first item is typically newest)
        if items:
            first_item = items[0]

            first_pubdate = first_item.find('pubDate')
            if first_pubdate is not None and first_pubdate.text:
                self.source_latest_pubdate = first_pubdate.text.strip()

            first_link = first_item.find('link')
            if first_link is not None and first_link.text:
                self.source_latest_link = first_link.text.strip()

        print(f"Found {len(items)} episodes")
        if self.source_latest_pubdate:
            print(f"Latest episode: {self.source_latest_pubdate}")

        # Format existing podcast:chapters elements for readability
        self._format_existing_chapters(items)


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

    def _format_existing_chapters(self, items: list) -> None:
        """
        Format existing podcast:chapters elements for better readability.

        Args:
            items: List of item elements
        """
        for item in items:
            # Find podcast:chapters element
            chapters = item.find('{https://podcastindex.org/namespace/1.0}chapters')
            if chapters is not None:
                self._add_newline_before_element(item, chapters)

    def _add_newline_before_element(self, parent: etree._Element, element: etree._Element) -> None:
        """
        Add a newline before an element by setting the tail of the previous sibling.

        Args:
            parent: Parent element
            element: Element to add newline before
        """
        children = list(parent)
        idx = children.index(element)
        if idx > 0:
            prev_elem = children[idx - 1]
            prev_elem.tail = '\n        '

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
