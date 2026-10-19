"""Channel-level metadata (guid, funding, podroll, ...) and feed housekeeping."""

from datetime import datetime, timedelta
from email.utils import format_datetime, parsedate_to_datetime
from typing import Dict, List, Optional, Self
from zoneinfo import ZoneInfo

from lxml import etree

from src.common.base_feed import BaseFeed
from src.common.namespaces import ATOM, PODCAST


class ChannelMixin(BaseFeed):
    """FeedEnricher methods for channel-level metadata (guid, funding, podroll, ...) and feed housekeeping."""

    def add_funding(
        self,
        url: str,
        message: str = "Support the show"
    ) -> Self:
        """
        Add podcast:funding tag to channel.

        Args:
            url: URL to funding page (Patreon, etc)
            message: Message to display

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        funding_elem = etree.Element(
            f'{PODCAST}funding',
            url=url
        )
        funding_elem.text = message

        self.channel.append(funding_elem)
        print(f"✓ Added funding link: {url}")
        return self

    def add_guid(
        self,
        guid: str
    ) -> Self:
        """
        Add podcast:guid tag to uniquely identify the podcast.

        This is the globally unique identifier for the podcast that stays
        the same even if the feed URL changes. This allows podcast apps to
        continue tracking the podcast across URL changes.

        Args:
            guid: UUID v5 or other globally unique identifier
                 Example: "ead4c236-bf58-58c6-a2c6-a6b28d128cb6"

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        # Remove existing guid if present
        existing = self.channel.find(f'{PODCAST}guid')
        if existing is not None:
            self.channel.remove(existing)

        guid_elem = etree.Element(
            f'{PODCAST}guid'
        )
        guid_elem.text = guid

        self.channel.append(guid_elem)
        print(f"✓ Added podcast:guid: {guid}")
        return self

    def add_medium(
        self,
        medium: str = "podcast"
    ) -> Self:
        """
        Add podcast:medium tag.

        Args:
            medium: Medium type (podcast, music, video, film, audiobook, newsletter, blog)

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        medium_elem = etree.Element(
            f'{PODCAST}medium'
        )
        medium_elem.text = medium

        self.channel.append(medium_elem)
        print(f"✓ Added medium: {medium}")
        return self

    def add_podroll(
        self,
        podcasts: List[Dict[str, str]]
    ) -> Self:
        """
        Add podcast:podroll tag to recommend other podcasts.

        Args:
            podcasts: List of podcast dicts with keys:
                - url: Feed URL (required)
                - title: Podcast title (optional but recommended)
                - feedGuid: podcast:guid (required per spec, will use URL hash if missing)

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        podroll_elem = etree.Element(
            f'{PODCAST}podroll'
        )

        for podcast in podcasts:
            attrs = {'feedUrl': podcast['url']}

            # feedGuid is required per spec
            if 'feedGuid' in podcast:
                attrs['feedGuid'] = podcast['feedGuid']

            # Add optional attributes
            if 'title' in podcast:
                attrs['title'] = podcast['title']

            etree.SubElement(
                podroll_elem,
                f'{PODCAST}remoteItem',
                **attrs
            )

        self.channel.append(podroll_elem)
        print(f"✓ Added podroll with {len(podcasts)} recommended podcasts")
        return self

    def add_update_frequency(
        self,
        complete: bool = True,
        frequency: Optional[int] = None,
        dtstart: Optional[str] = None,
        rrule: Optional[str] = None
    ) -> Self:
        """
        Add podcast:updateFrequency tag.

        Args:
            complete: Whether the feed is complete (no more episodes coming)
            frequency: Number of episodes per time period (e.g., 2 for biweekly)
            dtstart: ISO 8601 date when schedule started (e.g., "2020-01-01")
            rrule: iCalendar RRULE for recurrence (e.g., "FREQ=WEEKLY;INTERVAL=2")

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        freq_elem = etree.Element(
            f'{PODCAST}updateFrequency'
        )

        if complete:
            freq_elem.set('complete', 'true')
            freq_elem.text = "complete"
            print("✓ Added update frequency: complete (no more episodes)")
        else:
            if frequency:
                freq_elem.text = str(frequency)
                if dtstart:
                    freq_elem.set('dtstart', dtstart)
                if rrule:
                    freq_elem.set('rrule', rrule)
                    print(f"✓ Added update frequency: {frequency} episodes per period (rrule: {rrule})")
                else:
                    print(f"✓ Added update frequency: {frequency} episodes per period")
            else:
                freq_elem.text = "1"
                print("✓ Added update frequency: irregular schedule")

        self.channel.append(freq_elem)
        return self

    def add_op3_prefix(self) -> Self:
        """
        Add OP3 (Open Podcast Prefix Project) analytics to episode enclosures.
        Prefixes enclosure URLs with https://op3.dev/e/ to enable
        privacy-respecting download tracking.

        For HTTPS URLs, the protocol is stripped (e.g., https://example.com/file.mp3
        becomes https://op3.dev/e/example.com/file.mp3). For HTTP URLs, the full
        URL including protocol is kept.

        This provides free, public stats without compromising listener privacy.
        Stats page: https://op3.dev/show/[your-show-guid]

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        OP3_PREFIX = "https://op3.dev/e/"
        items = self.channel.findall('item')
        prefixed_count = 0

        for item in items:
            enclosure = item.find('enclosure')
            if enclosure is not None:
                url = enclosure.get('url')
                if url and not url.startswith(OP3_PREFIX):
                    # Strip https:// prefix if present (http:// URLs keep the protocol)
                    if url.startswith('https://'):
                        url = url[8:]  # Remove 'https://'
                    enclosure.set('url', OP3_PREFIX + url)
                    prefixed_count += 1

        print(f"✓ Added OP3 analytics prefix to {prefixed_count} episode enclosures")
        print("  Stats will be available at: https://op3.dev/show/[your-show-guid]")
        return self

    def format_podcast_elements(self) -> Self:
        """
        Format podcast elements for better readability.
        Adds newlines before all podcast:season, podcast:episode, and podcast:person elements.

        This should be called after all enrichment methods have been run.

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        items = self.channel.findall('item')
        for item in items:
            # Add newline before all podcast:season elements
            seasons = item.findall(f'{PODCAST}season')
            for season in seasons:
                self._add_newline_before_element(item, season)

            # Add newline before all podcast:episode elements
            episodes = item.findall(f'{PODCAST}episode')
            for episode in episodes:
                self._add_newline_before_element(item, episode)

            # Add newline before all podcast:person elements
            persons = item.findall(f'{PODCAST}person')
            for person in persons:
                self._add_newline_before_element(item, person)

        print("✓ Formatted podcast elements for better readability")
        return self

    def update_atom_link(self, url: str) -> Self:
        """
        Update atom:link to point to the actual feed URL.

        The atom:link with rel="self" should point to the feed's own URL,
        not the original source. This is important for feed validators and
        podcast apps to correctly identify the feed location.

        Args:
            url: The actual URL where this feed is published

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        # Find atom:link with rel="self"
        for link in self.channel.findall(f'{ATOM}link'):
            if link.get('rel') == 'self':
                old_url = link.get('href')
                link.set('href', url)
                print(f"✓ Updated atom:link from {old_url} to {url}")
                return self

        # If no atom:link exists, create one
        atom_link = etree.Element(
            f'{ATOM}link',
            href=url,
            rel='self',
            type='application/rss+xml'
        )
        # Insert after title
        title = self.channel.find('title')
        if title is not None:
            title_idx = list(self.channel).index(title)
            self.channel.insert(title_idx + 1, atom_link)
            print(f"✓ Added atom:link: {url}")
        else:
            self.channel.insert(0, atom_link)
            print(f"✓ Added atom:link: {url}")

        return self

    def update_generator(self, text: str) -> Self:
        """
        Update generator tag to reflect the actual generator.

        Args:
            text: Generator description (e.g., "podcast-feed-updater v1.0")

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        generator = self.channel.find('generator')
        if generator is not None:
            old_text = generator.text
            generator.text = text
            print(f"✓ Updated generator from '{old_text}' to '{text}'")
        else:
            # Create generator element if it doesn't exist
            generator = etree.Element('generator')
            generator.text = text
            # Insert after pubDate if it exists
            pubdate = self.channel.find('pubDate')
            if pubdate is not None:
                pubdate_idx = list(self.channel).index(pubdate)
                self.channel.insert(pubdate_idx + 1, generator)
            else:
                self.channel.append(generator)
            print(f"✓ Added generator: '{text}'")

        return self

    def update_lastBuildDate(self, timezone: str = "UTC") -> Self:
        """
        Update or add lastBuildDate with current timestamp.

        lastBuildDate indicates when the feed was last generated/updated.
        This is useful for feed readers to know when to check for updates.

        Args:
            timezone: IANA timezone for the timestamp (e.g. "Europe/Oslo"), so it
                matches the pubDates regardless of where the script runs

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        timestamp = format_datetime(datetime.now(ZoneInfo(timezone)))

        lastbuilddate = self.channel.find('lastBuildDate')
        if lastbuilddate is not None:
            lastbuilddate.text = timestamp
            print(f"✓ Updated lastBuildDate: {timestamp}")
        else:
            # Create lastBuildDate element
            lastbuilddate = etree.Element('lastBuildDate')
            lastbuilddate.text = timestamp
            # Insert after generator if it exists, otherwise after pubDate
            generator = self.channel.find('generator')
            if generator is not None:
                generator_idx = list(self.channel).index(generator)
                self.channel.insert(generator_idx + 1, lastbuilddate)
            else:
                pubdate = self.channel.find('pubDate')
                if pubdate is not None:
                    pubdate_idx = list(self.channel).index(pubdate)
                    self.channel.insert(pubdate_idx + 1, lastbuilddate)
                else:
                    self.channel.append(lastbuilddate)
            print(f"✓ Added lastBuildDate: {timestamp}")

        return self

    def shift_latest_episode_pubdate(self, hours: int = 6) -> Self:
        """
        Shift the pubDate of the newest episode (first <item>) by `hours` hours.

        Experimental: probes how podcast clients react when the newest
        episode's pubDate moves after publish. When the next episode lands,
        the previously-shifted item falls back to its original time because
        only the current newest item is touched on each run.

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        newest_item = self.channel.find('item')
        pubdate_elem = newest_item.find('pubDate') if newest_item is not None else None
        if pubdate_elem is None or not pubdate_elem.text:
            print("⚠ Newest item has no pubDate, skipping pubDate shift")
            return self

        original = pubdate_elem.text
        shifted = format_datetime(parsedate_to_datetime(original) + timedelta(hours=hours))
        pubdate_elem.text = shifted
        print(f"✓ Shifted newest episode pubDate by {hours}h: {original} → {shifted}")
        return self
