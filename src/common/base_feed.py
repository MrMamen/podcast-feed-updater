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
        self.source_episode_count: Optional[int] = None
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
        self.source_episode_count = len(items)

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

    def check_if_changed(self, output_file: str) -> bool:
        """
        Check if source feed has new or updated episodes compared to existing output.
        Uses both pubDate and link of latest episode for comparison.

        Args:
            output_file: Path to existing output file to compare against

        Returns:
            True if feed has new/updated episodes (or output doesn't exist), False otherwise
        """
        # If output doesn't exist, we need to generate it
        if not os.path.exists(output_file):
            print("ℹ Output file doesn't exist, generating...")
            return True

        # If we haven't fetched the source feed yet, do it now
        if self.source_latest_pubdate is None:
            self.fetch_feed()

        # If source has no pubDate or link, fall back to always regenerate
        if not self.source_latest_pubdate or not self.source_latest_link:
            print("ℹ No pubDate/link found in source, regenerating...")
            return True

        # Check cached pubDate and link
        cache_file = output_file + '.cache'
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    lines = f.read().strip().split('\n')
                    if len(lines) >= 2:
                        cached_pubdate = lines[0]
                        cached_link = lines[1]
                    else:
                        # Old format, regenerate
                        print("ℹ Old cache format, regenerating...")
                        return True

                # Check if both match
                pubdate_match = cached_pubdate == self.source_latest_pubdate
                link_match = cached_link == self.source_latest_link

                if pubdate_match and link_match:
                    print(f"ℹ No changes detected")
                    print(f"  Latest: {self.source_latest_pubdate}")
                    return False
                elif not pubdate_match:
                    print(f"ℹ New episode detected!")
                    print(f"  Previous: {cached_pubdate}")
                    print(f"  Current:  {self.source_latest_pubdate}")
                    return True
                else:  # link changed but pubdate same
                    print(f"ℹ Episode updated!")
                    print(f"  Date: {self.source_latest_pubdate}")
                    print(f"  Link changed (episode was modified)")
                    return True

            except Exception as e:
                print(f"ℹ Could not read cache file: {e}")
                return True
        else:
            print("ℹ No cache file found, generating...")
            return True

    def save_latest_pubdate(self, output_file: str) -> None:
        """
        Save latest episode pubDate and link to cache file for future comparisons.

        Args:
            output_file: Path to output file (cache will be saved as output_file.cache)
        """
        if self.source_latest_pubdate and self.source_latest_link:
            cache_file = output_file + '.cache'
            with open(cache_file, 'w') as f:
                f.write(f"{self.source_latest_pubdate}\n{self.source_latest_link}\n")
            print(f"✓ Saved episode metadata to cache")

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
