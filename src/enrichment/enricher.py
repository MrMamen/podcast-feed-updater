"""
Feed Enricher - Add Podcasting 2.0 tags to existing feeds.
Preserves all original content while adding new metadata.
"""

from lxml import etree
from typing import List, Dict, Optional
import requests
import json
from src.common.base_feed import BaseFeed


class FeedEnricher(BaseFeed):
    """Enrich podcast feeds with Podcasting 2.0 tags."""

    def validate_no_conflicts(self) -> 'FeedEnricher':
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
        item_tags_to_check = ['season', 'episode', 'person']

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
            for i, item in enumerate(items):
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
                "Update enrich_cdspill.py to either:\n"
                "  1. Stop adding these tags (remove method calls)\n"
                "  2. Modify the enricher to handle existing tags\n"
                "  3. Add explicit override logic if needed\n"
            )
            raise ValueError(error_msg)

        print("✓ Validation passed: No conflicting Podcasting 2.0 tags found")
        return self

    def set_beta_title(self, suffix: str = " (Beta)") -> 'FeedEnricher':
        """
        Add suffix to feed title for beta testing.

        Args:
            suffix: Suffix to add to title (default: " (Beta)")

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        # Find and update title
        title_elem = self.channel.find('title')
        if title_elem is not None and title_elem.text:
            if suffix not in title_elem.text:
                title_elem.text = title_elem.text + suffix
                print(f"✓ Updated title to: {title_elem.text}")

        # Also update itunes:title if present
        itunes_title = self.channel.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}title')
        if itunes_title is not None and itunes_title.text:
            if suffix not in itunes_title.text:
                itunes_title.text = itunes_title.text + suffix

        return self

    def add_channel_persons(
        self,
        persons: List[Dict[str, str]]
    ) -> 'FeedEnricher':
        """
        Add default hosts to channel level.

        Args:
            persons: List of person dicts with keys: name, role, img, href

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        # Ensure podcast namespace is registered
        self._ensure_podcast_namespace()

        # Add persons to channel
        for person_data in persons:
            person_elem = etree.Element(
                '{https://podcastindex.org/namespace/1.0}person',
                role=person_data.get('role', 'host')
            )
            person_elem.text = person_data['name']

            if 'img' in person_data:
                person_elem.set('img', person_data['img'])
            if 'href' in person_data:
                person_elem.set('href', person_data['href'])

            # Insert after last itunes tag for organization
            inserted = False
            for i, elem in enumerate(self.channel):
                if 'itunes' in elem.tag and i + 1 < len(self.channel):
                    if 'itunes' not in self.channel[i + 1].tag:
                        self.channel.insert(i + 1, person_elem)
                        inserted = True
                        break

            if not inserted:
                self.channel.append(person_elem)

        print(f"✓ Added {len(persons)} default host(s) to channel")
        return self

    def add_podcast_season_episode(self) -> 'FeedEnricher':
        """
        Add podcast:season and podcast:episode tags to all episodes.
        Uses itunes:season and itunes:episode as source.
        For cd SPILL: Season 1 = Vår 2020, Season 2 = Høst 2020, etc.

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        # Season name mapping (S1 = Vår 2020, S2 = Høst 2020, etc.)
        def get_season_name(season_num: int) -> str:
            """Generate season name from number."""
            if season_num <= 0:
                return f"Sesong {season_num}"

            # Calculate year and season
            year = 2020 + (season_num - 1) // 2
            is_spring = (season_num % 2) == 1

            season_name = "Vår" if is_spring else "Høst"
            return f"{season_name} {year}"

        items = self.channel.findall('item')
        added_count = 0

        for item in items:
            # Find itunes:season and itunes:episode
            season_elem = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}season')
            episode_elem = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}episode')

            if season_elem is not None and season_elem.text:
                season_num = int(season_elem.text)
                season_name = get_season_name(season_num)

                # Add podcast:season
                podcast_season = etree.Element(
                    '{https://podcastindex.org/namespace/1.0}season',
                    name=season_name
                )
                podcast_season.text = str(season_num)
                item.append(podcast_season)

            if episode_elem is not None and episode_elem.text:
                # Add podcast:episode
                podcast_episode = etree.Element(
                    '{https://podcastindex.org/namespace/1.0}episode'
                )
                podcast_episode.text = episode_elem.text
                item.append(podcast_episode)

            if season_elem is not None or episode_elem is not None:
                added_count += 1

        print(f"✓ Added podcast:season and podcast:episode tags to {added_count} episodes")
        return self

    def auto_detect_guests_from_titles(
        self,
        pattern: str = r'med (.+?)(?:\s*\(|$)',
        known_guests: Optional[Dict[str, Dict[str, str]]] = None,
        split_multiple: bool = True
    ) -> 'FeedEnricher':
        """
        Automatically detect and add guests from episode titles.

        Args:
            pattern: Regex pattern to extract guest names (default: "med Guest Name")
            known_guests: Optional dict mapping guest names to additional info
                         Example: {"Roar Granevang": {"href": "https://...", "img": "..."}}
                         Can include 'alias' key to normalize name variations:
                         {"Aksel Bjerke": {"alias": "Aksel M. Bjerke"}}
            split_multiple: If True, split multiple guests separated by " og " (default: True)

        Returns:
            Self for chaining
        """
        import re

        if self.channel is None:
            raise ValueError("Must fetch feed first")

        if known_guests is None:
            known_guests = {}

        items = self.channel.findall('item')
        guest_count = 0
        normalizations = []  # Track normalizations for reporting

        for item in items:
            title_elem = item.find('title')
            if title_elem is None or not title_elem.text:
                continue

            title = title_elem.text

            # Try to extract guest name(s) from title
            match = re.search(pattern, title, re.IGNORECASE)
            if match:
                guest_names_raw = match.group(1).strip()

                # Remove episode number if present (e.g., " (#120)")
                guest_names_raw = re.sub(r'\s*\(#?\d+\)$', '', guest_names_raw)

                # Split multiple guests if enabled
                if split_multiple and ' og ' in guest_names_raw.lower():
                    # Split on " og " (case insensitive)
                    guest_names = re.split(r'\s+og\s+', guest_names_raw, flags=re.IGNORECASE)
                else:
                    guest_names = [guest_names_raw]

                # Create person element for each guest
                for guest_name in guest_names:
                    guest_name = guest_name.strip()
                    if not guest_name:
                        continue

                    # Check for alias/normalization
                    original_name = guest_name
                    if guest_name in known_guests and 'alias' in known_guests[guest_name]:
                        normalized_name = known_guests[guest_name]['alias']
                        normalizations.append(f"  '{original_name}' → '{normalized_name}'")
                        guest_name = normalized_name

                    person_elem = etree.Element(
                        '{https://podcastindex.org/namespace/1.0}person',
                        role='guest'
                    )
                    person_elem.text = guest_name

                    # Add additional info if available (check both original and normalized name)
                    guest_info = known_guests.get(original_name, {})
                    if not guest_info:
                        guest_info = known_guests.get(guest_name, {})

                    if guest_info:
                        if 'href' in guest_info:
                            person_elem.set('href', guest_info['href'])
                        if 'img' in guest_info:
                            person_elem.set('img', guest_info['img'])

                    item.append(person_elem)
                    guest_count += 1

        print(f"✓ Auto-detected and added {guest_count} guests from episode titles")

        # Report normalizations if any
        if normalizations:
            print(f"\n  Name normalizations applied:")
            for norm in sorted(set(normalizations)):
                print(norm)

        return self

    def add_episode_persons(
        self,
        episode_mapping: Dict[str, List[Dict[str, str]]]
    ) -> 'FeedEnricher':
        """
        Add persons to specific episodes.

        Args:
            episode_mapping: Dict mapping episode title/guid to list of persons
                            Example: {"Episode Title": [{"name": "...", "role": "guest"}]}

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        items = self.channel.findall('item')
        matched = 0

        for item in items:
            # Try to match by title
            title_elem = item.find('title')
            title = title_elem.text if title_elem is not None else ''

            # Try to match by guid
            guid_elem = item.find('guid')
            guid = guid_elem.text if guid_elem is not None else ''

            # Check if this episode has person mappings
            persons = None
            if title in episode_mapping:
                persons = episode_mapping[title]
            elif guid in episode_mapping:
                persons = episode_mapping[guid]

            # Also try partial title match (useful for "with Guest Name" patterns)
            if not persons:
                for key in episode_mapping:
                    if key.lower() in title.lower():
                        persons = episode_mapping[key]
                        break

            if persons:
                for person_data in persons:
                    person_elem = etree.Element(
                        '{https://podcastindex.org/namespace/1.0}person',
                        role=person_data.get('role', 'guest')
                    )
                    person_elem.text = person_data['name']

                    if 'img' in person_data:
                        person_elem.set('img', person_data['img'])
                    if 'href' in person_data:
                        person_elem.set('href', person_data['href'])

                    item.append(person_elem)

                matched += 1

        print(f"✓ Added persons to {matched} episodes")
        return self

    def add_funding(
        self,
        url: str,
        message: str = "Support the show"
    ) -> 'FeedEnricher':
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
            '{https://podcastindex.org/namespace/1.0}funding',
            url=url
        )
        funding_elem.text = message

        self.channel.append(funding_elem)
        print(f"✓ Added funding link: {url}")
        return self

    def add_social_interact(
        self,
        protocol: str,
        uri: str,
        account_id: Optional[str] = None
    ) -> 'FeedEnricher':
        """
        Add podcast:socialInteract tag.

        Args:
            protocol: Protocol (activitypub, twitter, etc)
            uri: URI for interaction
            account_id: Optional account ID

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        social_elem = etree.Element(
            '{https://podcastindex.org/namespace/1.0}socialInteract',
            protocol=protocol,
            uri=uri
        )
        if account_id:
            social_elem.set('accountId', account_id)

        self.channel.append(social_elem)
        print(f"✓ Added social interact: {protocol} ({uri})")
        return self

    def add_guid(
        self,
        guid: str
    ) -> 'FeedEnricher':
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
        existing = self.channel.find('{https://podcastindex.org/namespace/1.0}guid')
        if existing is not None:
            self.channel.remove(existing)

        guid_elem = etree.Element(
            '{https://podcastindex.org/namespace/1.0}guid'
        )
        guid_elem.text = guid

        self.channel.append(guid_elem)
        print(f"✓ Added podcast:guid: {guid}")
        return self

    def add_medium(
        self,
        medium: str = "podcast"
    ) -> 'FeedEnricher':
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
            '{https://podcastindex.org/namespace/1.0}medium'
        )
        medium_elem.text = medium

        self.channel.append(medium_elem)
        print(f"✓ Added medium: {medium}")
        return self

    def add_podroll(
        self,
        podcasts: List[Dict[str, str]]
    ) -> 'FeedEnricher':
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
            '{https://podcastindex.org/namespace/1.0}podroll'
        )

        for podcast in podcasts:
            attrs = {'feedUrl': podcast['url']}

            # feedGuid is required per spec
            if 'feedGuid' in podcast:
                attrs['feedGuid'] = podcast['feedGuid']

            # Add optional attributes
            if 'feedTitle' in podcast:
                attrs['feedTitle'] = podcast['feedTitle']

            remote_elem = etree.SubElement(
                podroll_elem,
                '{https://podcastindex.org/namespace/1.0}remoteItem',
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
    ) -> 'FeedEnricher':
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
            '{https://podcastindex.org/namespace/1.0}updateFrequency'
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

    def add_op3_prefix(self) -> 'FeedEnricher':
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
        print(f"  Stats will be available at: https://op3.dev/show/[your-show-guid]")
        return self

    def convert_json_chapters_to_psc(self) -> 'FeedEnricher':
        """
        Convert podcast:chapters JSON references to Podlove Simple Chapters (PSC) format.

        Fetches JSON chapter files from podcast:chapters URLs and converts them to
        inline psc:chapters XML format for better client compatibility.

        JSON format (Podcasting 2.0):
            {"version": "1.2.0", "chapters": [{"startTime": 0, "title": "Intro"}]}

        PSC format (Podlove Simple Chapters):
            <psc:chapters version="1.2">
                <psc:chapter start="00:00:00" title="Intro" />
            </psc:chapters>

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        # Ensure PSC namespace is registered
        psc_ns = "http://podlove.org/simple-chapters"
        if psc_ns not in self.root.nsmap.values():
            # Add namespace to root element
            nsmap = self.root.nsmap.copy()
            nsmap['psc'] = psc_ns
            # Create new root with updated namespaces
            new_root = etree.Element(self.root.tag, nsmap=nsmap)
            new_root.text = self.root.text
            new_root.tail = self.root.tail
            for key, value in self.root.attrib.items():
                new_root.set(key, value)
            for child in self.root:
                new_root.append(child)
            self.root = new_root
            self.channel = self.root.find('channel')

        items = self.channel.findall('item')
        converted_count = 0
        failed_count = 0

        for item in items:
            # Find podcast:chapters element
            podcast_chapters = item.find('{https://podcastindex.org/namespace/1.0}chapters')

            if podcast_chapters is not None:
                json_url = podcast_chapters.get('url')
                if json_url and json_url.endswith('.json'):
                    try:
                        # Fetch JSON chapters
                        response = requests.get(json_url, timeout=10)
                        response.raise_for_status()
                        chapters_data = response.json()

                        # Create PSC chapters element
                        psc_chapters = etree.Element(
                            f'{{{psc_ns}}}chapters',
                            version="1.2"
                        )

                        # Convert each chapter
                        if 'chapters' in chapters_data:
                            for chapter in chapters_data['chapters']:
                                start_time = chapter.get('startTime', 0)
                                title = chapter.get('title', '')

                                # Convert seconds to HH:MM:SS format
                                hours = int(start_time // 3600)
                                minutes = int((start_time % 3600) // 60)
                                seconds = int(start_time % 60)
                                time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

                                # Create chapter element
                                attrs = {
                                    'start': time_str,
                                    'title': title
                                }

                                # Add optional attributes
                                if 'url' in chapter:
                                    attrs['href'] = chapter['url']
                                if 'img' in chapter:
                                    attrs['image'] = chapter['img']

                                psc_chapter = etree.SubElement(
                                    psc_chapters,
                                    f'{{{psc_ns}}}chapter',
                                    **attrs
                                )

                            # Add PSC chapters to item (after podcast:chapters)
                            chapter_index = list(item).index(podcast_chapters)
                            item.insert(chapter_index + 1, psc_chapters)
                            converted_count += 1

                    except Exception as e:
                        failed_count += 1
                        # Silently skip episodes with failed chapter conversions
                        continue

        print(f"✓ Converted {converted_count} JSON chapters to Podlove Simple Chapters format")
        if failed_count > 0:
            print(f"  ⚠ {failed_count} episodes failed to convert (JSON not accessible)")

        return self

    def write_feed(self, output_file: str) -> None:
        """
        Write enriched feed to file.

        Args:
            output_file: Output file path
        """
        super().write_feed(output_file)
        print(f"✓ Enriched feed written to: {output_file}")
