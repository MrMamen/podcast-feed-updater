"""
Feed Enricher - Add Podcasting 2.0 tags to existing feeds.
Preserves all original content while adding new metadata.
"""

from lxml import etree
from typing import List, Dict, Optional
import requests
import json
import os
import shutil
import string
from urllib.parse import urlparse
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

    def remove_episode_numbers_from_titles(self, pattern: str = r'\s*\(#?\d+\)$') -> 'FeedEnricher':
        """
        Remove episode numbers from episode titles.

        Args:
            pattern: Regex pattern to match episode numbers (default: matches "(#123)" or "(123)" at end of title)

        Returns:
            Self for chaining
        """
        import re

        if self.channel is None:
            raise ValueError("Must fetch feed first")

        items = self.channel.findall('item')
        removed_count = 0

        for item in items:
            # Update <title>
            title_elem = item.find('title')
            if title_elem is not None and title_elem.text:
                new_title = re.sub(pattern, '', title_elem.text).strip()
                if new_title != title_elem.text:
                    title_elem.text = new_title
                    removed_count += 1

            # Also update <itunes:title> if present
            itunes_title = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}title')
            if itunes_title is not None and itunes_title.text:
                itunes_title.text = re.sub(pattern, '', itunes_title.text).strip()

        print(f"✓ Removed episode numbers from {removed_count} episode titles")
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

        The podcast:episode tag includes a display attribute showing both
        the season episode number and total episode number (e.g., "2 (#80)").

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

        # First pass: count episodes per season (feed is in reverse chronological order)
        season_episode_counts = {}
        for item in items:
            season_elem = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}season')
            if season_elem is not None and season_elem.text:
                season_num = int(season_elem.text)
                if season_num not in season_episode_counts:
                    season_episode_counts[season_num] = 0
                season_episode_counts[season_num] += 1

        # Second pass: add podcast:season and podcast:episode tags
        season_counters = {}
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
                total_episode_num = int(episode_elem.text)

                # Calculate season episode number (reverse chronological order)
                if season_elem is not None and season_elem.text:
                    season_num = int(season_elem.text)

                    # Initialize counter for this season if not present
                    if season_num not in season_counters:
                        season_counters[season_num] = season_episode_counts[season_num]

                    # Get the episode number within the season
                    season_episode_num = season_counters[season_num]
                    season_counters[season_num] -= 1

                    # Create display attribute: "2 (#80)"
                    display_value = f"{season_episode_num} (#{total_episode_num})"

                    # Add podcast:episode with display attribute
                    podcast_episode = etree.Element(
                        '{https://podcastindex.org/namespace/1.0}episode',
                        display=display_value
                    )
                    podcast_episode.text = str(total_episode_num)
                    item.append(podcast_episode)
                else:
                    # No season info, just use total episode number
                    podcast_episode = etree.Element(
                        '{https://podcastindex.org/namespace/1.0}episode'
                    )
                    podcast_episode.text = str(total_episode_num)
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
                         Can include 'extra_episodes' list to add guest to specific episodes by GUID:
                         {"Terje Høiback": {"href": "...", "extra_episodes": [{"guid": "...", "note": "..."}]}}
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
        extra_episodes_count = 0
        normalizations = []  # Track normalizations for reporting
        missing_metadata = []  # Track guests without profile images

        # First pass: Handle extra_episodes (manual additions by GUID)
        for guest_name, guest_info in known_guests.items():
            if 'extra_episodes' not in guest_info:
                continue

            # Skip if this is an alias entry
            if 'alias' in guest_info:
                continue

            for episode_spec in guest_info['extra_episodes']:
                episode_guid = episode_spec['guid']

                # Find item with matching GUID
                for item in items:
                    guid_elem = item.find('guid')
                    if guid_elem is None or not guid_elem.text:
                        continue

                    if guid_elem.text == episode_guid:
                        # Add guest to this episode
                        person_elem = etree.Element(
                            '{https://podcastindex.org/namespace/1.0}person',
                            role='guest'
                        )
                        person_elem.text = guest_name

                        if 'href' in guest_info:
                            person_elem.set('href', guest_info['href'])
                        if 'img' in guest_info:
                            person_elem.set('img', guest_info['img'])

                        item.append(person_elem)
                        extra_episodes_count += 1
                        break

        # Second pass: Auto-detect from titles
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

                    has_href = False
                    if guest_info:
                        if 'href' in guest_info:
                            person_elem.set('href', guest_info['href'])
                            has_href = True
                        if 'img' in guest_info:
                            person_elem.set('img', guest_info['img'])

                    # Track guests without href (Podchaser URL)
                    # img is nice to have but not critical
                    if not has_href:
                        missing_metadata.append({
                            'name': guest_name,
                            'original_name': original_name if original_name != guest_name else None,
                            'episode': title
                        })

                    item.append(person_elem)
                    guest_count += 1

        # Report summary
        total_added = guest_count + extra_episodes_count
        if extra_episodes_count > 0:
            print(f"✓ Added {total_added} guest appearances ({guest_count} auto-detected from titles, {extra_episodes_count} from extra_episodes)")
        else:
            print(f"✓ Auto-detected and added {guest_count} guests from episode titles")

        # Report normalizations if any
        if normalizations:
            print(f"\n  Name normalizations applied:")
            for norm in sorted(set(normalizations)):
                print(norm)

        # Report guests without metadata
        if missing_metadata:
            # Group by guest name to avoid duplicates
            unique_missing = {}
            for guest in missing_metadata:
                name = guest['name']
                if name not in unique_missing:
                    unique_missing[name] = {
                        'original_name': guest['original_name'],
                        'episodes': []
                    }
                unique_missing[name]['episodes'].append(guest['episode'])

            print(f"\n⚠ Found {len(unique_missing)} guest(s) without Podchaser URL (href):")
            for name, info in sorted(unique_missing.items()):
                episode_count = len(info['episodes'])
                if episode_count == 1:
                    print(f"  - {name} (1 episode)")
                else:
                    print(f"  - {name} ({episode_count} episodes)")

                # Show original name if it was normalized from an alias
                if info['original_name']:
                    print(f"    (detected as '{info['original_name']}' in titles)")

            print(f"\n💡 Add Podchaser profile with:")
            print(f"   uv run python3 lookup_guest.py \"Guest Name\"")

            # If there are guests that might need aliases
            detected_names = [info['original_name'] for info in unique_missing.values()
                            if info['original_name']]
            if detected_names:
                print(f"\n💡 If name variations exist, add aliases with:")
                print(f"   uv run python3 lookup_guest.py \"Full Name\" --alias \"Short Name\"")

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
        account_id: Optional[str] = None,
        account_url: Optional[str] = None,
        priority: Optional[int] = None
    ) -> 'FeedEnricher':
        """
        Add podcast:socialInteract tag.

        Args:
            protocol: Protocol (activitypub, twitter, etc)
            uri: URI for interaction
            account_id: Optional account ID
            account_url: Optional account URL
            priority: Optional priority (lower numbers = higher priority)

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
        if account_url:
            social_elem.set('accountUrl', account_url)
        if priority is not None:
            social_elem.set('priority', str(priority))

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
            if 'title' in podcast:
                attrs['title'] = podcast['title']

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

    def convert_json_chapters_to_psc(
        self,
        chapters_dir: str = "chapters",
        output_dir: str = "docs/chapters",
        base_url: str = "https://mrmamen.github.io/podcast-feed-updater/chapters"
    ) -> 'FeedEnricher':
        """
        Convert podcast:chapters JSON references to Podlove Simple Chapters (PSC) format.

        First attempts to load chapters from local JSON files matching Podbean filenames.
        If found, copies to output directory and updates podcast:chapters URL.
        If not found, fetches from podcast:chapters URLs.
        Supports toc: false flag to exclude chapters from table of contents.

        JSON format (Podcasting 2.0):
            {"version": "1.2.0", "chapters": [{"startTime": 0, "title": "Intro", "toc": false}]}

        PSC format (Podlove Simple Chapters):
            <psc:chapters version="1.2">
                <psc:chapter start="00:00:00" title="Intro" />
            </psc:chapters>

        Args:
            chapters_dir: Directory containing source chapter JSON files (default: "chapters")
            output_dir: Directory to copy chapter files for hosting (default: "docs/chapters")
            base_url: Base URL for hosted chapter files (default: GitHub Pages URL)

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
        local_count = 0
        used_local_files = set()  # Track which local files are used

        # Create output directory for hosted chapter files
        os.makedirs(output_dir, exist_ok=True)

        # Helper function for word-based matching
        def normalize_words(text):
            """Remove punctuation and split into words for fuzzy matching."""
            translator = str.maketrans('', '', string.punctuation)
            clean_text = text.translate(translator)
            return set(clean_text.lower().split())

        # Get podcast logo for standard chapters
        podcast_logo = None
        channel_image = self.channel.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}image')
        if channel_image is not None:
            podcast_logo = channel_image.get('href')

        # Build episode index for previous/next episode cover art
        # Also build a mapping from game names to their episode cover art
        episode_covers = []
        episode_titles_to_covers = {}

        for item in items:
            itunes_image = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}image')
            cover_url = itunes_image.get('href') if itunes_image is not None else None
            episode_covers.append(cover_url)

            # Extract game name from episode title for cross-referencing
            title_elem = item.find('title')
            if title_elem is not None and cover_url:
                full_title = title_elem.text or ''
                # Remove guest names: "Rainbow Six med Jostein Hakestad" -> "Rainbow Six"
                game_name = full_title.split(' med ')[0].strip()
                # Store both exact case and lowercase for matching
                episode_titles_to_covers[game_name.lower()] = cover_url
                # Also store with colon variations for better matching
                # "Rainbow Six: Rogue Spear" -> also match "Rainbow Six"
                if ':' in game_name:
                    base_name = game_name.split(':')[0].strip()
                    episode_titles_to_covers[base_name.lower()] = cover_url

        for item_index, item in enumerate(items):
            # Find podcast:chapters element
            podcast_chapters = item.find('{https://podcastindex.org/namespace/1.0}chapters')

            if podcast_chapters is not None:
                json_url = podcast_chapters.get('url')
                if json_url and json_url.endswith('.json'):
                    try:
                        chapters_data = None
                        source_type = "remote"

                        # Extract filename from URL (e.g., "Outrun_chapters.json")
                        url_path = urlparse(json_url).path
                        filename = os.path.basename(url_path)
                        local_file = os.path.join(chapters_dir, filename)

                        # Try to load local chapter file first
                        if os.path.exists(local_file):
                            try:
                                with open(local_file, 'r', encoding='utf-8') as f:
                                    chapters_data = json.load(f)
                                source_type = "local"
                                local_count += 1
                                used_local_files.add(filename)

                                # Validate against Podbean version
                                try:
                                    response = requests.get(json_url, timeout=10)
                                    response.raise_for_status()
                                    podbean_data = response.json()

                                    local_chapter_count = len(chapters_data.get('chapters', []))
                                    podbean_chapter_count = len(podbean_data.get('chapters', []))

                                    if local_chapter_count != podbean_chapter_count:
                                        title_elem = item.find('title')
                                        episode_title = title_elem.text if title_elem is not None else 'Unknown'
                                        print(f"  ⚠️  Chapter count mismatch: {episode_title}")
                                        print(f"      Local file: {local_chapter_count} chapters ({filename})")
                                        print(f"      Podbean:    {podbean_chapter_count} chapters")
                                        print(f"      Check if the local file needs updating")

                                except Exception:
                                    # If we can't fetch Podbean version for comparison, that's okay
                                    pass

                            except Exception as e:
                                # Fall back to remote if local file is invalid
                                print(f"  ⚠️  Failed to load local file {filename}: {e}")
                                pass

                        # Fall back to fetching from URL if no local file
                        if chapters_data is None:
                            response = requests.get(json_url, timeout=10)
                            response.raise_for_status()
                            chapters_data = response.json()

                        # Process chapters data (sorting, intro, images) before saving and PSC conversion
                        if 'chapters' in chapters_data:
                            original_chapters = chapters_data['chapters']

                            # Get episode title for reporting
                            title_elem = item.find('title')
                            episode_title = title_elem.text if title_elem is not None else 'Unknown'

                            # Detect if chapters are unsorted in source JSON
                            is_unsorted = any(
                                original_chapters[i].get('startTime', 0) > original_chapters[i+1].get('startTime', 0)
                                for i in range(len(original_chapters) - 1)
                            )

                            if is_unsorted:
                                source_label = "local file" if source_type == "local" else json_url
                                print(f"  ⚠️  Unsorted chapters detected: {episode_title}")
                                print(f"      Source: {source_label}")

                            # Sort chapters by startTime to ensure chronological order
                            sorted_chapters = sorted(
                                original_chapters,
                                key=lambda ch: ch.get('startTime', 0)
                            )

                            # Check if first chapter starts at 0:00 (excluding hidden chapters)
                            visible_chapters = [ch for ch in sorted_chapters if ch.get('toc', True)]
                            missing_intro = (
                                len(visible_chapters) > 0 and
                                visible_chapters[0].get('startTime', 0) > 0
                            )

                            if missing_intro:
                                print(f"  ⚠️  Missing 00:00 intro chapter: {episode_title}")
                                print(f"      Source JSON: {json_url}")

                                # Add intro chapter at 00:00
                                intro_chapter = {
                                    'startTime': 0,
                                    'title': 'Intro'
                                }
                                sorted_chapters.insert(0, intro_chapter)

                            # Update chapters_data with sorted (and possibly intro-added) chapters
                            chapters_data['chapters'] = sorted_chapters

                            # Get episode cover art for image injection
                            cover_art_url = episode_covers[item_index]

                            # Get previous and next episode cover art
                            prev_cover_url = episode_covers[item_index + 1] if item_index + 1 < len(episode_covers) else None
                            next_cover_url = episode_covers[item_index - 1] if item_index > 0 else None

                            # Inject images for standard chapters (for ALL episodes, not just local)
                            images_injected = 0
                            for chapter in sorted_chapters:
                                # Skip if chapter already has an image
                                if 'img' in chapter:
                                    continue

                                chapter_title = chapter.get('title', '').strip()
                                chapter_title_lower = chapter_title.lower()
                                start_time = chapter.get('startTime', 0)

                                # Match patterns for image injection
                                image_to_inject = None

                                # FIRST CHAPTER: Always gets episode cover (regardless of title)
                                if start_time == 0 and cover_art_url:
                                    image_to_inject = cover_art_url

                                # Episode cover art patterns
                                elif cover_art_url and (
                                    chapter_title.startswith("Dagens") or
                                    chapter_title_lower.startswith("idag:") or
                                    chapter_title.startswith("Episodens") or
                                    chapter_title == "Hva går spillet ut på?" or
                                    chapter_title == "Har det holdt seg?" or
                                    chapter_title == "Kommentarer fra sosiale medier" or
                                    "fra sosiale medier" in chapter_title_lower or
                                    "facebook" in chapter_title_lower or
                                    "twitter" in chapter_title_lower or
                                    "bluesky" in chapter_title_lower
                                ):
                                    image_to_inject = cover_art_url

                                # Podcast logo patterns
                                elif podcast_logo and "cd spill" in chapter_title_lower:
                                    image_to_inject = podcast_logo

                                # Previous episode cover art patterns
                                elif prev_cover_url and (
                                    "fra sist" in chapter_title_lower or
                                    "fra forrige" in chapter_title_lower
                                ):
                                    image_to_inject = prev_cover_url

                                # Next episode cover art patterns
                                elif next_cover_url and (
                                    "neste" in chapter_title_lower
                                ):
                                    image_to_inject = next_cover_url

                                # Music and tech chapters (using episode cover for now)
                                # TODO: Replace with dedicated images when available:
                                #   - "Musikken" -> music note icon
                                #   - "Tech Specs" -> technical icon
                                elif cover_art_url and (
                                    "musikk" in chapter_title_lower or
                                    "tech" in chapter_title_lower
                                ):
                                    image_to_inject = cover_art_url

                                # Cross-reference: Match chapter title against episode game names
                                # Example: "Home Alone" chapter in OutRun episode gets Home Alone episode cover
                                elif chapter_title_lower in episode_titles_to_covers:
                                    image_to_inject = episode_titles_to_covers[chapter_title_lower]

                                # Exact suffix matching: Chapter ends with episode name
                                # Example: "Historien i Duke Nukem" → Duke Nukem episode
                                elif not image_to_inject:
                                    for episode_name, cover in episode_titles_to_covers.items():
                                        if len(episode_name) > 3 and chapter_title_lower.endswith(episode_name):
                                            image_to_inject = cover
                                            break

                                # "I forhold til [game]" - cross-reference to that game's episode
                                elif "i forhold til" in chapter_title_lower:
                                    game_name = chapter_title_lower.split("i forhold til", 1)[1].strip()
                                    if game_name in episode_titles_to_covers:
                                        image_to_inject = episode_titles_to_covers[game_name]

                                # "Ligner på [game]" - cross-reference to that game's episode
                                elif "ligner på" in chapter_title_lower:
                                    game_name = chapter_title_lower.split("ligner på", 1)[1].strip()
                                    if game_name in episode_titles_to_covers:
                                        image_to_inject = episode_titles_to_covers[game_name]

                                # "Kommentarer fra [episode]" - match episode name (not previous, not social media)
                                elif chapter_title_lower.startswith("kommentarer fra "):
                                    # Skip if it's social media or previous episode (already handled above)
                                    if not any(x in chapter_title_lower for x in ["sosiale medier", "forrige", "sist", "facebook", "twitter", "bluesky"]):
                                        # Extract potential episode name
                                        potential_name = chapter_title_lower.replace("kommentarer fra ", "").strip()

                                        # Try word-based matching for better partial matches
                                        # This helps match "Kommentarer fra Freddi Fisk" to "freddi fisk og humongous entertainment"
                                        potential_words = normalize_words(potential_name)

                                        best_match = None
                                        best_match_score = 0

                                        for episode_name, cover in episode_titles_to_covers.items():
                                            if len(episode_name) <= 3:  # Skip very short episode names
                                                continue

                                            episode_words = normalize_words(episode_name)
                                            common_words = potential_words & episode_words

                                            # Calculate match score: number of overlapping words
                                            match_score = len(common_words)

                                            # Good match if:
                                            # - At least 2 words overlap, OR
                                            # - All words from potential_name are found in episode_name
                                            if match_score >= 2 or (len(potential_words) > 0 and match_score == len(potential_words)):
                                                if match_score > best_match_score:
                                                    best_match = cover
                                                    best_match_score = match_score

                                        if best_match:
                                            image_to_inject = best_match

                                # Inject the image
                                if image_to_inject:
                                    chapter['img'] = image_to_inject
                                    images_injected += 1

                            # Save enriched JSON to output directory (for ALL episodes)
                            output_file = os.path.join(output_dir, filename)
                            with open(output_file, 'w', encoding='utf-8') as f:
                                json.dump(chapters_data, f, indent=2, ensure_ascii=False)

                            # Update podcast:chapters URL to point to our hosted version (for ALL episodes)
                            new_url = f"{base_url}/{filename}"
                            podcast_chapters.set('url', new_url)

                        # Create PSC chapters element
                        psc_chapters = etree.Element(
                            f'{{{psc_ns}}}chapters',
                            version="1.2"
                        )

                        # Convert chapters to PSC format (chapters are already sorted and have intro)
                        if 'chapters' in chapters_data:
                            # Use the already processed chapters from chapters_data
                            processed_chapters = chapters_data['chapters']

                            for chapter in processed_chapters:
                                # Skip hidden chapters (toc: false)
                                if chapter.get('toc', True) is False:
                                    continue

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

                            # Add newline before psc:chapters for better readability
                            self._add_newline_before_element(item, psc_chapters)

                            converted_count += 1

                    except Exception as e:
                        failed_count += 1
                        # Silently skip episodes with failed chapter conversions
                        continue

        print(f"✓ Converted {converted_count} JSON chapters to Podlove Simple Chapters format")
        if local_count > 0:
            print(f"  📁 {local_count} from local files (with toc: false support)")
        if failed_count > 0:
            print(f"  ⚠ {failed_count} episodes failed to convert (JSON not accessible)")

        # Check for unused local chapter files
        if os.path.exists(chapters_dir):
            all_local_files = set()
            for filename in os.listdir(chapters_dir):
                if filename.endswith('.json') and not filename.startswith('.'):
                    all_local_files.add(filename)

            unused_files = all_local_files - used_local_files
            if unused_files:
                print(f"  ⚠️  Found {len(unused_files)} unused chapter file(s) in {chapters_dir}/")
                for filename in sorted(unused_files):
                    print(f"      - {filename} (check filename matches Podbean URL)")

        return self

    def format_podcast_elements(self) -> 'FeedEnricher':
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
            seasons = item.findall('{https://podcastindex.org/namespace/1.0}season')
            for season in seasons:
                self._add_newline_before_element(item, season)

            # Add newline before all podcast:episode elements
            episodes = item.findall('{https://podcastindex.org/namespace/1.0}episode')
            for episode in episodes:
                self._add_newline_before_element(item, episode)

            # Add newline before all podcast:person elements
            persons = item.findall('{https://podcastindex.org/namespace/1.0}person')
            for person in persons:
                self._add_newline_before_element(item, person)

        print("✓ Formatted podcast elements for better readability")
        return self

    def _format_youtube_timestamp(self, time_str: str) -> str:
        """
        Convert HH:MM:SS to YouTube format (strip leading zeros).

        Examples:
            "00:00:00" → "0:00"
            "00:12:34" → "12:34"
            "01:23:45" → "1:23:45"

        Args:
            time_str: Time string in HH:MM:SS format

        Returns:
            YouTube-friendly time format
        """
        parts = time_str.split(':')
        if len(parts) != 3:
            return time_str  # Invalid format, return as-is

        hours, minutes, seconds = parts
        hours = int(hours)
        minutes = int(minutes)

        if hours > 0:
            # Format: H:MM:SS (preserve leading zero in minutes)
            return f"{hours}:{minutes:02d}:{seconds}"
        else:
            # Format: M:SS or MM:SS (no leading zero on minutes)
            return f"{minutes}:{seconds}"

    def restore_episode_numbers_to_titles(self, format: str = ' (#{episode})') -> 'FeedEnricher':
        """
        Restore episode numbers to episode titles from itunes:episode tags.
        Inverse operation of remove_episode_numbers_from_titles().

        This is useful for feeds like YouTube that display episode numbers differently
        than podcast apps. Skips bonus episodes (episodeType=bonus) as they should
        not have episode numbers in titles.

        Args:
            format: Format string with {episode} placeholder (default: ' (#{episode})')

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        items = self.channel.findall('item')
        restored_count = 0
        skipped_bonus = 0

        for item in items:
            # Skip bonus episodes (they should not have episode numbers in titles)
            episode_type = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}episodeType')
            if episode_type is not None and episode_type.text == 'bonus':
                skipped_bonus += 1
                continue

            episode_elem = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}episode')
            if episode_elem is None or not episode_elem.text:
                continue

            episode_num = episode_elem.text.strip()
            suffix = format.format(episode=episode_num)

            # Update <title>
            title_elem = item.find('title')
            if title_elem is not None and title_elem.text:
                if suffix not in title_elem.text:  # Avoid duplicates
                    title_elem.text = title_elem.text + suffix
                    restored_count += 1

            # Update <itunes:title> if present
            itunes_title = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}title')
            if itunes_title is not None and itunes_title.text:
                if suffix not in itunes_title.text:
                    itunes_title.text = itunes_title.text + suffix

        print(f"✓ Restored episode numbers to {restored_count} episode titles (skipped {skipped_bonus} bonus episodes)")
        return self

    def add_chapter_timestamps_to_description(self, separator: str = '\n\n') -> 'FeedEnricher':
        """
        Extract chapter timestamps from psc:chapters and append to episode descriptions.
        Formats chapters as "0:00 Intro\n12:34 Chapter Title\n..." for YouTube compatibility.

        YouTube doesn't support podcast:chapters or psc:chapters tags, but it does
        support timestamps in the description text. This method extracts chapter
        information and appends it as plain text.

        Args:
            separator: Separator between original description and timestamps (default: '\n\n')

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        psc_ns = "http://podlove.org/simple-chapters"
        items = self.channel.findall('item')
        updated_count = 0

        for item in items:
            # Find psc:chapters element (must be present from convert_json_chapters_to_psc)
            psc_chapters = item.find(f'{{{psc_ns}}}chapters')
            if psc_chapters is None:
                continue

            # Extract all chapter elements
            chapters = psc_chapters.findall(f'{{{psc_ns}}}chapter')
            if not chapters:
                continue

            # Build timestamp text block
            timestamp_lines = []
            for chapter in chapters:
                start_time = chapter.get('start', '00:00:00')
                title = chapter.get('title', '')

                # Convert to YouTube format (e.g., "0:00", "12:34", "1:23:45")
                youtube_time = self._format_youtube_timestamp(start_time)
                timestamp_lines.append(f"{youtube_time} {title}")

            if not timestamp_lines:
                continue

            timestamp_text = '\n'.join(timestamp_lines)

            # Update <description>
            desc_elem = item.find('description')
            if desc_elem is not None and desc_elem.text:
                if timestamp_text not in desc_elem.text:
                    desc_elem.text = desc_elem.text + separator + timestamp_text

            # Update <content:encoded>
            content_elem = item.find('{http://purl.org/rss/1.0/modules/content/}encoded')
            if content_elem is not None and content_elem.text:
                if timestamp_text not in content_elem.text:
                    content_elem.text = content_elem.text + separator + timestamp_text

            updated_count += 1

        print(f"✓ Added chapter timestamps to {updated_count} episode descriptions")
        return self

    def remove_chapter_tags(self) -> 'FeedEnricher':
        """
        Remove podcast:chapters and psc:chapters tags from episodes.

        This is useful for feeds like YouTube that don't support chapter tags
        but use timestamps in descriptions instead. Removing these tags reduces
        feed size without losing functionality.

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        podcast_ns = 'https://podcastindex.org/namespace/1.0'
        psc_ns = "http://podlove.org/simple-chapters"
        items = self.channel.findall('item')

        removed_podcast_chapters = 0
        removed_psc_chapters = 0

        for item in items:
            # Remove podcast:chapters
            podcast_chapters = item.find(f'{{{podcast_ns}}}chapters')
            if podcast_chapters is not None:
                item.remove(podcast_chapters)
                removed_podcast_chapters += 1

            # Remove psc:chapters
            psc_chapters = item.find(f'{{{psc_ns}}}chapters')
            if psc_chapters is not None:
                item.remove(psc_chapters)
                removed_psc_chapters += 1

        print(f"✓ Removed {removed_podcast_chapters} podcast:chapters and {removed_psc_chapters} psc:chapters tags")
        return self

    def update_atom_link(self, url: str) -> 'FeedEnricher':
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

        atom_ns = '{http://www.w3.org/2005/Atom}'

        # Find atom:link with rel="self"
        for link in self.channel.findall(f'{atom_ns}link'):
            if link.get('rel') == 'self':
                old_url = link.get('href')
                link.set('href', url)
                print(f"✓ Updated atom:link from {old_url} to {url}")
                return self

        # If no atom:link exists, create one
        atom_link = etree.Element(
            f'{atom_ns}link',
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

    def update_generator(self, text: str) -> 'FeedEnricher':
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

    def update_lastBuildDate(self) -> 'FeedEnricher':
        """
        Update or add lastBuildDate with current timestamp.

        lastBuildDate indicates when the feed was last generated/updated.
        This is useful for feed readers to know when to check for updates.

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        from datetime import datetime, timezone, timedelta
        from email.utils import format_datetime

        # Generate RFC 2822 formatted date with Norwegian timezone (+0100)
        # This ensures consistency with pubDate regardless of where the script runs
        norway_tz = timezone(timedelta(hours=1))
        now = datetime.now(norway_tz)
        timestamp = format_datetime(now)

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

    def write_feed(self, output_file: str) -> None:
        """
        Write enriched feed to file.

        Args:
            output_file: Output file path
        """
        super().write_feed(output_file)
        print(f"✓ Enriched feed written to: {output_file}")
