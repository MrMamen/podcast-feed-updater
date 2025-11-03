"""
Feed Merger - Combines items from one feed with metadata from another.
"""

import requests
from xml.etree import ElementTree as ET
from xml.dom import minidom
from typing import List, Optional


class FeedMerger:
    """Merge feed items with target feed metadata."""

    def __init__(self, items_source_url: str, metadata_source_url: str):
        """
        Initialize merger.

        Args:
            items_source_url: URL of feed to get items from
            metadata_source_url: URL of feed to get channel metadata from
        """
        self.items_url = items_source_url
        self.metadata_url = metadata_source_url
        self.items_root = None
        self.metadata_root = None
        self.items = []
        self.metadata_channel = None

    def fetch_feeds(self) -> None:
        """Fetch both feeds."""
        print(f"Fetching items from: {self.items_url}")
        response = requests.get(self.items_url, timeout=30)
        response.raise_for_status()
        self.items_root = ET.fromstring(response.content)

        print(f"Fetching metadata from: {self.metadata_url}")
        response = requests.get(self.metadata_url, timeout=30)
        response.raise_for_status()
        self.metadata_root = ET.fromstring(response.content)

        # Extract items from source
        items_channel = self.items_root.find('channel')
        if items_channel is not None:
            self.items = items_channel.findall('item')
            print(f"Found {len(self.items)} items in source feed")

        # Get metadata channel
        self.metadata_channel = self.metadata_root.find('channel')
        if self.metadata_channel is None:
            raise ValueError("No channel found in metadata feed")

    def merge(self, output_file: str, pretty: bool = True) -> None:
        """
        Merge items with metadata and write output.

        Args:
            output_file: Output file path
            pretty: Pretty-print XML
        """
        if not self.items or not self.metadata_channel:
            raise ValueError("Must fetch feeds before merging")

        # Create new root with metadata feed's attributes
        new_root = ET.Element('rss')
        for key, value in self.metadata_root.attrib.items():
            new_root.set(key, value)

        # Create new channel
        new_channel = ET.SubElement(new_root, 'channel')

        # Copy all channel-level metadata (everything except items)
        for elem in self.metadata_channel:
            if elem.tag != 'item':
                new_channel.append(elem)

        # Add items from source feed
        for item in self.items:
            new_channel.append(item)

        # Write output
        self._write_xml(new_root, output_file, pretty)

        print(f"✓ Merged feed written to: {output_file}")
        print(f"  - Channel metadata from: {self.metadata_url}")
        print(f"  - {len(self.items)} items from: {self.items_url}")

    def _write_xml(self, root: ET.Element, output_file: str, pretty: bool) -> None:
        """Write XML to file."""
        if pretty:
            xml_str = ET.tostring(root, encoding='unicode')
            dom = minidom.parseString(xml_str)
            pretty_xml = dom.toprettyxml(indent='  ')
            lines = [line for line in pretty_xml.split('\n') if line.strip()]
            pretty_xml = '\n'.join(lines)

            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(pretty_xml)
        else:
            tree = ET.ElementTree(root)
            tree.write(output_file, encoding='utf-8', xml_declaration=True)


class FeedSplitter:
    """Split a feed into multiple feeds based on title patterns."""

    def __init__(self, source_url: str):
        """
        Initialize splitter.

        Args:
            source_url: URL of source feed to split
        """
        self.source_url = source_url
        self.root = None
        self.channel = None
        self.items = []

    def fetch_feed(self) -> None:
        """Fetch source feed."""
        print(f"Fetching source feed: {self.source_url}")
        response = requests.get(self.source_url, timeout=30)
        response.raise_for_status()

        self.root = ET.fromstring(response.content)
        self.channel = self.root.find('channel')

        if self.channel is None:
            raise ValueError("No channel found in feed")

        self.items = self.channel.findall('item')
        print(f"Found {len(self.items)} items in source feed")

    def split_by_patterns(
        self,
        patterns: List[tuple],
        metadata_urls: List[str],
        output_files: List[str]
    ) -> None:
        """
        Split feed by multiple patterns and merge with metadata.

        Args:
            patterns: List of (pattern, keep_matching) tuples
            metadata_urls: List of metadata feed URLs (one per pattern + one for "rest")
            output_files: List of output file paths (one per pattern + one for "rest")
        """
        import re

        if len(patterns) + 1 != len(metadata_urls) or len(patterns) + 1 != len(output_files):
            raise ValueError("Must provide metadata_urls and output_files for each pattern + one for 'rest'")

        # Categorize items
        categorized = [[] for _ in range(len(patterns) + 1)]

        for item in self.items:
            title_elem = item.find('title')
            title = title_elem.text if title_elem is not None and title_elem.text else ''

            matched = False
            for idx, (pattern, keep_matching) in enumerate(patterns):
                regex = re.compile(pattern, re.IGNORECASE)
                if regex.search(title):
                    if keep_matching:
                        categorized[idx].append(item)
                        matched = True
                        break

            # If not matched by any pattern, goes to "rest" category
            if not matched:
                categorized[-1].append(item)

        # Print statistics
        print(f"\nSplit results:")
        for idx, (pattern, _) in enumerate(patterns):
            print(f"  Pattern '{pattern}': {len(categorized[idx])} items")
        print(f"  Rest (no match): {len(categorized[-1])} items")

        # Create merged feeds
        for idx, items in enumerate(categorized):
            if not items:
                print(f"\n⚠ Warning: No items for category {idx}, skipping")
                continue

            print(f"\nCreating feed {idx + 1}/{len(categorized)}...")

            # Fetch metadata feed
            print(f"  Fetching metadata from: {metadata_urls[idx]}")
            response = requests.get(metadata_urls[idx], timeout=30)
            response.raise_for_status()
            metadata_root = ET.fromstring(response.content)
            metadata_channel = metadata_root.find('channel')

            if metadata_channel is None:
                print(f"  ⚠ Warning: No channel in metadata feed, skipping")
                continue

            # Create merged feed
            new_root = ET.Element('rss')
            for key, value in metadata_root.attrib.items():
                new_root.set(key, value)

            new_channel = ET.SubElement(new_root, 'channel')

            # Copy metadata (except items)
            for elem in metadata_channel:
                if elem.tag != 'item':
                    new_channel.append(elem)

            # Add filtered items
            for item in items:
                new_channel.append(item)

            # Write output
            self._write_xml(new_root, output_files[idx])

            print(f"  ✓ Written: {output_files[idx]} ({len(items)} items)")

    def _write_xml(self, root: ET.Element, output_file: str) -> None:
        """Write XML to file."""
        xml_str = ET.tostring(root, encoding='unicode')
        dom = minidom.parseString(xml_str)
        pretty_xml = dom.toprettyxml(indent='  ')
        lines = [line for line in pretty_xml.split('\n') if line.strip()]
        pretty_xml = '\n'.join(lines)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(pretty_xml)
