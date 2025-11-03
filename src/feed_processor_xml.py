"""
XML-based Podcast Feed Processor
Preserves original feed structure and all fields.
"""

import re
from typing import List, Optional, Callable
import requests
from xml.etree import ElementTree as ET
from xml.dom import minidom


class XMLPodcastFeedProcessor:
    """Feed processor that preserves original XML structure."""

    def __init__(self, source_feed_url: str):
        """
        Initialize the processor with a source feed URL.

        Args:
            source_feed_url: URL of the podcast RSS feed to process
        """
        self.source_url = source_feed_url
        self.tree = None
        self.root = None
        self.channel = None
        self.items = []
        self.filtered_items = []

    def fetch_feed(self) -> None:
        """Fetch and parse the source feed as XML."""
        print(f"Fetching feed from: {self.source_url}")

        response = requests.get(self.source_url, timeout=30)
        response.raise_for_status()

        # Parse XML
        self.root = ET.fromstring(response.content)
        self.channel = self.root.find('channel')

        if self.channel is None:
            raise ValueError("Invalid RSS feed: no channel element found")

        # Get all items
        self.items = self.channel.findall('item')
        print(f"Found {len(self.items)} episodes in feed")

    def _get_item_title(self, item: ET.Element) -> str:
        """Extract title from an item element."""
        title_elem = item.find('title')
        return title_elem.text if title_elem is not None and title_elem.text else ''

    def filter_by_title_pattern(
        self,
        pattern: str,
        keep_matching: bool = True
    ) -> 'XMLPodcastFeedProcessor':
        """
        Filter episodes based on title pattern.

        Args:
            pattern: Regex pattern to match against episode titles
            keep_matching: If True, keep matching episodes. If False, exclude them.

        Returns:
            Self for method chaining
        """
        if not self.items:
            raise ValueError("Must fetch feed before filtering")

        regex = re.compile(pattern, re.IGNORECASE)
        self.filtered_items = []

        for item in self.items:
            title = self._get_item_title(item)
            matches = bool(regex.search(title))

            if (keep_matching and matches) or (not keep_matching and not matches):
                self.filtered_items.append(item)

        print(f"Filter '{pattern}' resulted in {len(self.filtered_items)} episodes")
        return self

    def filter_by_custom_function(
        self,
        filter_func: Callable[[ET.Element], bool]
    ) -> 'XMLPodcastFeedProcessor':
        """
        Filter episodes using a custom function.

        Args:
            filter_func: Function that takes an item Element and returns True to keep it

        Returns:
            Self for method chaining
        """
        if not self.items:
            raise ValueError("Must fetch feed before filtering")

        self.filtered_items = [item for item in self.items if filter_func(item)]

        print(f"Custom filter resulted in {len(self.filtered_items)} episodes")
        return self

    def update_feed_metadata(
        self,
        title: Optional[str] = None,
        description: Optional[str] = None,
        link: Optional[str] = None
    ) -> 'XMLPodcastFeedProcessor':
        """
        Update feed-level metadata.

        Args:
            title: New feed title
            description: New feed description
            link: New feed link

        Returns:
            Self for method chaining
        """
        if title:
            title_elem = self.channel.find('title')
            if title_elem is not None:
                title_elem.text = title

        if description:
            desc_elem = self.channel.find('description')
            if desc_elem is not None:
                desc_elem.text = description

            # Also update iTunes subtitle if present
            itunes_subtitle = self.channel.find('.//{http://www.itunes.com/dtds/podcast-1.0.dtd}subtitle')
            if itunes_subtitle is not None:
                # Truncate to first 50 chars for subtitle
                itunes_subtitle.text = description[:50] + '…' if len(description) > 50 else description

        if link:
            link_elem = self.channel.find('link')
            if link_elem is not None:
                link_elem.text = link

        return self

    def generate_feed(
        self,
        output_file: str,
        feed_title: Optional[str] = None,
        feed_description: Optional[str] = None,
        feed_link: Optional[str] = None,
        pretty: bool = True
    ) -> None:
        """
        Generate a new RSS feed from filtered items.

        Args:
            output_file: Path to write the output feed
            feed_title: Override feed title
            feed_description: Override feed description
            feed_link: Override feed link
            pretty: Pretty-print the XML output
        """
        if not self.filtered_items:
            print("Warning: No items to generate feed from")
            return

        # Create a new tree with filtered items
        new_root = ET.Element('rss')

        # Copy all attributes from original root (version, namespaces, etc)
        for key, value in self.root.attrib.items():
            new_root.set(key, value)

        # Create new channel
        new_channel = ET.SubElement(new_root, 'channel')

        # Copy all channel-level elements (except items)
        for elem in self.channel:
            if elem.tag != 'item':
                new_channel.append(elem)

        # Update metadata if provided
        if feed_title or feed_description or feed_link:
            # We need to work with the copied elements
            if feed_title:
                title_elem = new_channel.find('title')
                if title_elem is not None:
                    title_elem.text = feed_title

            if feed_description:
                desc_elem = new_channel.find('description')
                if desc_elem is not None:
                    desc_elem.text = feed_description

                # Also update iTunes subtitle
                for elem in new_channel.iter():
                    if elem.tag.endswith('subtitle'):
                        elem.text = feed_description[:50] + '…' if len(feed_description) > 50 else feed_description

            if feed_link:
                link_elem = new_channel.find('link')
                if link_elem is not None:
                    link_elem.text = feed_link

        # Add filtered items
        for item in self.filtered_items:
            new_channel.append(item)

        # Write to file
        tree = ET.ElementTree(new_root)

        if pretty:
            # Pretty print using minidom
            xml_str = ET.tostring(new_root, encoding='unicode')
            dom = minidom.parseString(xml_str)
            pretty_xml = dom.toprettyxml(indent='  ')

            # Remove extra blank lines
            lines = [line for line in pretty_xml.split('\n') if line.strip()]
            pretty_xml = '\n'.join(lines)

            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(pretty_xml)
        else:
            tree.write(output_file, encoding='utf-8', xml_declaration=True)

        print(f"Generated feed written to: {output_file}")
        print(f"Total episodes in new feed: {len(self.filtered_items)}")


def create_filtered_feed_xml(
    source_url: str,
    output_file: str,
    title_pattern: Optional[str] = None,
    new_title: Optional[str] = None,
    new_description: Optional[str] = None,
) -> None:
    """
    Convenience function to create a filtered feed preserving XML structure.

    Args:
        source_url: Source feed URL
        output_file: Output file path
        title_pattern: Pattern to filter episode titles
        new_title: New feed title
        new_description: New feed description
    """
    processor = XMLPodcastFeedProcessor(source_url)
    processor.fetch_feed()

    if title_pattern:
        processor.filter_by_title_pattern(title_pattern)
    else:
        processor.filtered_items = processor.items

    processor.generate_feed(
        output_file,
        feed_title=new_title,
        feed_description=new_description
    )
