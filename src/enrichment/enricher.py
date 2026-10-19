"""
Feed Enricher - Add Podcasting 2.0 tags to existing feeds.
Preserves all original content while adding new metadata.
"""

from lxml import etree
from typing import Callable, List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor
import requests
import hashlib
import json
import os
import shutil
import string
from urllib.parse import urlparse
from src.common.base_feed import BaseFeed
from src.common.http import USER_AGENT
from src.common.podcast_utils import DEFAULT_EPISODE_NUMBER_SUFFIX, TitleRules


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
                "Update the podcast's podcast.toml or the pipeline to either:\n"
                "  1. Stop adding these tags (remove the config section)\n"
                "  2. Modify the enricher to handle existing tags\n"
                "  3. Add explicit override logic if needed\n"
            )
            raise ValueError(error_msg)

        print("✓ Validation passed: No conflicting Podcasting 2.0 tags found")
        return self

    def remove_episode_numbers_from_titles(
        self, pattern: str = DEFAULT_EPISODE_NUMBER_SUFFIX
    ) -> 'FeedEnricher':
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

    def add_podcast_season_episode(
        self, season_name: Optional[Callable[[int], str]] = None
    ) -> 'FeedEnricher':
        """
        Add podcast:season and podcast:episode tags to all episodes.
        Uses itunes:season and itunes:episode as source.

        The podcast:episode tag includes a display attribute showing both
        the season episode number and total episode number (e.g., "2 (#80)").

        Args:
            season_name: Function from season number to the podcast:season name
                attribute (see podcast_utils.season_namer); None adds no name

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

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

                # Add podcast:season
                podcast_season = etree.Element('{https://podcastindex.org/namespace/1.0}season')
                if season_name:
                    podcast_season.set('name', season_name(season_num))
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
        title_rules: Optional[TitleRules] = None,
        known_guests: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> 'FeedEnricher':
        """
        Automatically detect and add guests from episode titles.

        Args:
            title_rules: How guests are named in titles ("Game med Guest A og Guest B").
                         None: only extra_episodes are added.
            known_guests: Optional dict mapping guest names to additional info
                         Example: {"Roar Granevang": {"href": "https://...", "img": "..."}}
                         Can include 'alias' key to normalize name variations:
                         {"Aksel Bjerke": {"alias": "Aksel M. Bjerke"}}
                         Can include 'extra_episodes' list to add guest to specific episodes by GUID:
                         {"Terje Høiback": {"href": "...", "extra_episodes": [{"guid": "...", "note": "..."}]}}

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        if known_guests is None:
            known_guests = {}
        if title_rules is None:
            title_rules = TitleRules()

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
                        # Add guest to this episode (one person element per role)
                        roles = episode_spec.get('role', 'guest')
                        if isinstance(roles, str):
                            roles = [roles]

                        for role in roles:
                            person_elem = etree.Element(
                                '{https://podcastindex.org/namespace/1.0}person',
                                role=role
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

            # Create person element for each guest named in the title
            for guest_name in title_rules.extract_guests(title):
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

                # Look up canonical name first (guest_name is already normalized
                # from any alias). Falling back to original_name would return
                # an alias stub ({"alias": ...}) and miss the real href/img.
                guest_info = known_guests.get(guest_name, {})
                if not guest_info:
                    guest_info = known_guests.get(original_name, {})

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
            print("\n  Name normalizations applied:")
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

            print("\n💡 Add Podchaser profile with:")
            print("   uv run guests.py add \"Guest Name\"   (or: uv run guests.py refresh)")

            # If there are guests that might need aliases
            detected_names = [info['original_name'] for info in unique_missing.values()
                            if info['original_name']]
            if detected_names:
                print("\n💡 If name variations exist, add aliases with:")
                print("   uv run guests.py add \"Full Name\" --alias \"Short Name\"")

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

    @staticmethod
    def bluesky_post_url(at_uri: str) -> str:
        """Turn at://<did>/app.bsky.feed.post/<rkey> into a bsky.app web URL."""
        did, _, rkey = at_uri.removeprefix('at://').split('/')
        return f"https://bsky.app/profile/{did}/post/{rkey}"

    def add_bluesky_episode_social_interact(
        self,
        handle: str,
        article_domain: str,
        timezone: str = "Europe/Oslo",
    ) -> 'FeedEnricher':
        """
        Add item-level podcast:socialInteract (atproto) pointing to the
        Bluesky post announcing each episode.

        Posts are fetched from the public Bluesky API (no auth). A post is
        matched to an episode when it links to the episode's <link> article.
        Remaining posts linking to article_domain are matched by date when
        exactly one unmatched post and one unmatched episode share a day
        (catches ?p= short links in <link>). A failed fetch only warns.

        Args:
            handle: Bluesky handle, e.g. "cdspill.bsky.social"
            article_domain: Domain the posts link to, e.g. "spillhistorie.no"
            timezone: Timezone used to compare post and episode dates

        Returns:
            Self for chaining
        """
        from datetime import datetime
        from email.utils import parsedate_to_datetime
        from zoneinfo import ZoneInfo

        if self.channel is None:
            raise ValueError("Must fetch feed first")

        api = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
        posts = []  # (at_uri, local_date, article_urls)
        tz = ZoneInfo(timezone)
        cursor = None
        try:
            while True:
                params = {"actor": handle, "limit": 100, "filter": "posts_no_replies"}
                if cursor:
                    params["cursor"] = cursor
                response = requests.get(api, params=params, timeout=15)
                response.raise_for_status()
                data = response.json()
                for entry in data.get("feed", []):
                    if entry.get("reason"):  # repost
                        continue
                    post = entry["post"]
                    record = post["record"]
                    urls = [post.get("embed", {}).get("external", {}).get("uri")]
                    for facet in record.get("facets", []):
                        urls += [f.get("uri") for f in facet.get("features", [])]
                    urls = {u.rstrip('/') for u in urls if u and article_domain in u}
                    if not urls:
                        continue
                    created = datetime.fromisoformat(record["createdAt"].replace('Z', '+00:00'))
                    posts.append((post["uri"], created.astimezone(tz).date(), urls))
                cursor = data.get("cursor")
                if not cursor or not data.get("feed"):
                    break
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"⚠️  Could not fetch Bluesky posts for {handle}, skipping: {e}")
            return self

        def add_tag(item, at_uri):
            etree.SubElement(
                item,
                '{https://podcastindex.org/namespace/1.0}socialInteract',
                protocol="atproto",
                uri=at_uri,
                accountId=f"@{handle}",
                accountUrl=f"https://bsky.app/profile/{handle}",
                priority="1",
            )

        # Oldest post first, so a later re-share doesn't win over the announcement
        posts.reverse()
        by_url = {}
        for at_uri, _, urls in posts:
            for url in urls:
                by_url.setdefault(url, at_uri)

        used = set()
        unmatched_items = []
        link_matches = 0
        for item in self.channel.findall('item'):
            link = (item.findtext('link') or '').strip().rstrip('/')
            at_uri = by_url.get(link)
            if at_uri and at_uri not in used:
                add_tag(item, at_uri)
                used.add(at_uri)
                link_matches += 1
            else:
                unmatched_items.append(item)

        def item_date(item):
            try:
                return parsedate_to_datetime(item.findtext('pubDate')).astimezone(tz).date()
            except (TypeError, ValueError):
                return None

        date_matches = 0
        free_posts = [p for p in posts if p[0] not in used]
        for item in unmatched_items:
            day = item_date(item)
            if day is None:
                continue
            same_day_posts = [p for p in free_posts if p[1] == day]
            same_day_items = [i for i in unmatched_items if item_date(i) == day]
            if len(same_day_posts) == 1 and len(same_day_items) == 1:
                add_tag(item, same_day_posts[0][0])
                free_posts.remove(same_day_posts[0])
                date_matches += 1

        print(f"✓ Added Bluesky socialInteract to {link_matches + date_matches} episodes "
              f"({link_matches} by article link, {date_matches} by date)")
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
        print("  Stats will be available at: https://op3.dev/show/[your-show-guid]")
        return self

    def add_language_to_transcripts(
        self,
        default_language: str = "no",
        overrides: dict[str, str] | None = None,
    ) -> 'FeedEnricher':
        """Add language attribute to all podcast:transcript tags.

        Args:
            default_language: ISO 639-1 language code for most episodes.
            overrides: {guid_substring: language_code} for exceptions.

        Returns:
            Self for chaining.
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        overrides = overrides or {}
        ns = "https://podcastindex.org/namespace/1.0"
        items = self.channel.findall('item')
        count = 0

        for item in items:
            transcript = item.find(f'{{{ns}}}transcript')
            if transcript is None:
                continue

            # Determine language from overrides (match on GUID substring)
            lang = default_language
            guid_el = item.find('guid')
            if guid_el is not None and guid_el.text:
                for guid_sub, override_lang in overrides.items():
                    if guid_sub in guid_el.text:
                        lang = override_lang
                        break

            transcript.set('language', lang)
            count += 1

        print(f"✓ Added language attribute to {count} podcast:transcript tags")
        return self

    def add_transcript_versions(self, workers: int = 8) -> 'FeedEnricher':
        """
        Append ?v=<ETag> to podcast:transcript URLs hosted on Podbean.

        Podbean keeps the same URL when a transcript is replaced, so the feed
        doesn't change and clients that cache transcripts by URL never see the
        new version. The ETag changes with the file, so the URL now does too.
        Podbean ignores unknown query parameters. URLs whose ETag can't be
        fetched are left unchanged.

        Args:
            workers: Number of parallel HEAD requests.

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        transcripts = [
            t for t in self.channel.iter('{https://podcastindex.org/namespace/1.0}transcript')
            if 'podbean.com' in urlparse(t.get('url', '')).netloc
        ]
        session = requests.Session()
        session.headers['User-Agent'] = USER_AGENT

        def fetch_etag(url: str) -> Optional[str]:
            try:
                response = session.head(url, allow_redirects=True, timeout=10)
                response.raise_for_status()
            except Exception:
                return None
            etag = response.headers.get('ETag', '')
            etag = etag.removeprefix('W/').strip('"')
            return etag or None

        with ThreadPoolExecutor(max_workers=workers) as executor:
            etags = list(executor.map(fetch_etag, [t.get('url') for t in transcripts]))

        versioned = 0
        for transcript, etag in zip(transcripts, etags):
            if etag:
                url = transcript.get('url').split('?v=')[0]
                separator = '&' if '?' in url else '?'
                transcript.set('url', f"{url}{separator}v={etag}")
                versioned += 1

        print(f"✓ Added version to {versioned} of {len(transcripts)} Podbean transcript URLs")
        if versioned < len(transcripts):
            print(f"  ⚠️  {len(transcripts) - versioned} without ETag, left unversioned")
        return self

    @staticmethod
    def _fetch_apple_episode_urls(apple_podcast_id: int, country: str = "us") -> Dict[str, str]:
        """
        Fetch Apple Podcasts episode URLs keyed by episode GUID via the iTunes lookup API.

        Returns an empty dict if the lookup fails, so chapter links are skipped
        without affecting the rest of the enrichment.
        """
        limit = 200  # Maximum the lookup API returns
        try:
            response = requests.get(
                "https://itunes.apple.com/lookup",
                params={"id": apple_podcast_id, "entity": "podcastEpisode",
                        "limit": limit, "country": country},
                timeout=20,
            )
            response.raise_for_status()
            results = response.json().get('results', [])
        except Exception as e:
            print(f"  ⚠️  Could not fetch Apple Podcasts episodes: {e}")
            return {}

        urls = {}
        for result in results:
            if result.get('wrapperType') != 'podcastEpisode':
                continue
            guid = result.get('episodeGuid')
            track_url = result.get('trackViewUrl')
            if guid and track_url:
                # Drop tracking parameter (&uo=4) and use the podcast's storefront
                track_url = track_url.split('&uo=')[0]
                track_url = track_url.replace('podcasts.apple.com/us/', f'podcasts.apple.com/{country}/')
                urls[guid] = track_url

        if len(urls) >= limit - 20:
            print(f"  ⚠️  Apple lookup returned {len(urls)} episodes (API max {limit}); "
                  f"older episodes will soon lack chapter links")
        return urls

    @staticmethod
    def _fetch_link_cover(url: str) -> Optional[str]:
        """
        Find a game cover for a chapter link to Steam, GOG or Wikipedia.

        Returns the image URL at the source (hotlinked, not downloaded), or None
        for other sites or when the lookup fails.
        """
        import re

        # Wikimedia requires contact info in the User-Agent
        headers = {"User-Agent": USER_AGENT}
        parsed = urlparse(url)
        host = parsed.netloc.lower()

        try:
            # Steam: portrait library cover, built from the app id in the link.
            # Older games lack it and fall back to the landscape store header.
            if host.endswith("steampowered.com"):
                match = re.search(r"/app/(\d+)", parsed.path)
                if not match:
                    return None
                base = f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{match.group(1)}"
                for name in ("library_600x900_2x.jpg", "library_600x900.jpg", "header.jpg"):
                    if requests.head(f"{base}/{name}", timeout=10).status_code == 200:
                        return f"{base}/{name}"
                return None

            # GOG: product id from the store page, then box art from the games API.
            # A wrong slug redirects to the store front, which has no product id.
            if host.endswith("gog.com") and "/game/" in parsed.path:
                page = requests.get(url, headers=headers, timeout=15)
                match = re.search(r'card-product="(\d+)"', page.text)
                if not match:
                    print(f"  ⚠️  No GOG product found for chapter link: {url}")
                    return None
                game = requests.get(f"https://api.gog.com/v2/games/{match.group(1)}", timeout=15).json()
                return game.get('_links', {}).get('boxArtImage', {}).get('href')

            # Wikipedia: the article's lead image. Box art is non-free, so allow any license.
            if host.endswith("wikipedia.org") and parsed.path.startswith("/wiki/"):
                from urllib.parse import unquote
                response = requests.get(
                    f"https://{host}/w/api.php",
                    params={"action": "query", "titles": unquote(parsed.path[len("/wiki/"):]),
                            "prop": "pageimages", "piprop": "original", "pilicense": "any",
                            "redirects": 1, "format": "json"},
                    headers=headers, timeout=15,
                )
                pages = response.json().get('query', {}).get('pages', {})
                source = next(iter(pages.values()), {}).get('original', {}).get('source')
                # Drop Wikimedia's utm tracking parameters
                return source.split('?')[0] if source else None
        except Exception as e:
            print(f"  ⚠️  Could not fetch cover for chapter link {url}: {e}")

        return None

    def convert_json_chapters_to_psc(
        self,
        base_url: str,
        chapters_dir: str = "chapters",
        output_dir: Optional[str] = None,
        images_dir: Optional[str] = None,
        include_psc_tags: bool = True,
        apple_podcast_id: Optional[int] = None,
        apple_country: str = "us",
        title_rules: Optional[TitleRules] = None,
    ) -> 'FeedEnricher':
        """
        Process chapter JSON files and optionally add Podlove Simple Chapters (PSC) tags.

        Always performs: loads local JSON (with image injection, sorting, intro-fill),
        saves enriched copy to output_dir, and rewrites podcast:chapters URL to base_url.
        Optionally (include_psc_tags=True): inserts <psc:chapters> inline for Spotify.

        First attempts to load chapters from local JSON files matching Podbean filenames.
        If not found, fetches from podcast:chapters URLs.
        Supports toc: false flag to exclude chapters from table of contents.

        JSON format (Podcasting 2.0):
            {"version": "1.2.0", "chapters": [{"startTime": 0, "title": "Intro", "toc": false}]}

        PSC format (Podlove Simple Chapters):
            <psc:chapters version="1.2">
                <psc:chapter start="00:00:00" title="Intro" />
            </psc:chapters>

        Args:
            base_url: Public URL that output_dir is published at
            chapters_dir: Directory containing local chapter JSON files, named like the
                files in the source feed; they take precedence over the source's
            output_dir: Directory to copy chapter files to for hosting. None skips hosting
                and leaves podcast:chapters URLs as they are, so variant feeds don't
                overwrite the chapter files the main feed publishes.
            images_dir: Directory with images for recurring chapters, copied to
                output_dir/images
            include_psc_tags: If True, insert <psc:chapters> inline (for Spotify variant).
                If False, only host JSON and rewrite URLs (for main feed).
            apple_podcast_id: If set, chapters whose image refers to another episode
                also get a "url" to that episode in Apple Podcasts. A "url" already in
                the chapter file is kept; "url": null disables the automatic link.
            apple_country: Apple Podcasts storefront for those links (e.g. "no")
            title_rules: Title conventions, so chapters can be matched against what
                other episodes are about ("Rainbow Six med Jostein" → "Rainbow Six")

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        # Ensure PSC namespace is registered (only needed when inserting PSC tags)
        psc_ns = "http://podlove.org/simple-chapters"
        if include_psc_tags and psc_ns not in self.root.nsmap.values():
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
        total_links = 0
        used_local_files = set()  # Track which local files are used

        # Create output directory for hosted chapter files, with the images for
        # recurring chapters
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            if images_dir:
                shutil.copytree(images_dir, os.path.join(output_dir, 'images'), dirs_exist_ok=True)
        music_image = f"{base_url}/images/music.jpg"
        tech_image = f"{base_url}/images/tech.jpg"
        social_media_image = f"{base_url}/images/social_media.jpg"

        # Helper function for word-based matching
        def normalize_words(text):
            """Remove punctuation and split into words for fuzzy matching."""
            translator = str.maketrans('', '', string.punctuation)
            clean_text = text.translate(translator)
            return set(clean_text.lower().split())

        # Whole-word prefix/suffix checks, so "doom" doesn't match "doomsday machine"
        # and "spillåret 1993" doesn't match "eventyrspillåret 1993"
        def starts_with_word(text, prefix):
            return text.startswith(prefix) and (
                len(text) == len(prefix) or not text[len(prefix)].isalnum()
            )

        def ends_with_word(text, suffix):
            start = len(text) - len(suffix)
            return text.endswith(suffix) and (start == 0 or not text[start - 1].isalnum())

        # Get podcast logo for standard chapters
        podcast_logo = None
        channel_image = self.channel.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}image')
        if channel_image is not None:
            podcast_logo = channel_image.get('href')

        if title_rules is None:
            title_rules = TitleRules()
        apple_urls = (self._fetch_apple_episode_urls(apple_podcast_id, apple_country)
                      if apple_podcast_id else {})
        # Chapter link -> cover image, so a link used in several chapters is looked up once
        link_covers = {}

        def link_cover(url):
            if url not in link_covers:
                link_covers[url] = self._fetch_link_cover(url)
            return link_covers[url]

        # Build episode index for previous/next episode cover art
        # Also build a mapping from game names to their episode cover art
        episode_covers = []
        episode_titles_to_covers = {}
        # Cover art -> Apple Podcasts URL, for linking chapters that match another episode.
        # Covers shared by several episodes are ambiguous and get no link.
        cover_to_apple_url = {}
        ambiguous_covers = set()

        for item in items:
            itunes_image = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}image')
            cover_url = itunes_image.get('href') if itunes_image is not None else None
            episode_covers.append(cover_url)

            guid_elem = item.find('guid')
            apple_url = apple_urls.get(guid_elem.text) if guid_elem is not None else None
            if cover_url:
                if cover_url in cover_to_apple_url or cover_url in ambiguous_covers:
                    ambiguous_covers.add(cover_url)
                    cover_to_apple_url.pop(cover_url, None)
                elif apple_url:
                    cover_to_apple_url[cover_url] = apple_url

            # Extract game name from episode title for cross-referencing
            title_elem = item.find('title')
            if title_elem is not None and cover_url:
                # Remove guest names: "Rainbow Six med Jostein Hakestad" -> "Rainbow Six"
                game_name = title_rules.subject(title_elem.text)
                # Normalize apostrophes: replace curly quotes (U+2019) with straight quotes (U+0027)
                # This ensures matching with chapter files that use straight quotes
                game_name_normalized = game_name.replace('\u2019', "'")
                # Store both exact case and lowercase for matching
                episode_titles_to_covers[game_name_normalized.lower()] = cover_url
                # Also store with colon variations for better matching
                # "Rainbow Six: Rogue Spear" -> also match "Rainbow Six"
                if ':' in game_name_normalized:
                    base_name = game_name_normalized.split(':')[0].strip()
                    episode_titles_to_covers[base_name.lower()] = cover_url

        for item_index, item in enumerate(items):
            # Find podcast:chapters element
            podcast_chapters = item.find('{https://podcastindex.org/namespace/1.0}chapters')

            if podcast_chapters is not None:
                json_url = podcast_chapters.get('url')
                if json_url and urlparse(json_url).path.endswith('.json'):
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
                                        print("      Check if the local file needs updating")

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
                            links_injected = 0
                            for chapter in sorted_chapters:
                                chapter_title = chapter.get('title', '').strip()

                                # Skip if chapter already has an image (including null to disable auto-matching)
                                # You can use "img": null in chapter file to prevent auto-matching
                                # (empty/null values are cleaned up before saving output)
                                if 'img' in chapter:
                                    continue

                                # Normalize apostrophes for consistent matching
                                chapter_title_normalized = chapter_title.replace('\u2019', "'")
                                chapter_title_lower = chapter_title_normalized.lower()
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
                                    chapter_title == "Har det holdt seg?"
                                ):
                                    image_to_inject = cover_art_url
                                # Social media comments
                                elif (
                                    "sosiale medier" in chapter_title_lower or
                                    "facebook" in chapter_title_lower or
                                    "twitter" in chapter_title_lower or
                                    "bluesky" in chapter_title_lower
                                ):
                                    image_to_inject = social_media_image

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

                                # Music and tech chapters
                                elif "musikk" in chapter_title_lower:
                                    image_to_inject = music_image
                                elif "tech" in chapter_title_lower:
                                    image_to_inject = tech_image

                                # Chapter links to Steam, GOG or Wikipedia: use the game's cover.
                                # Takes precedence over episode matching, so "Syndicate Wars" linked
                                # to GOG doesn't get the Syndicate episode cover.
                                elif chapter.get('url') and link_cover(chapter['url']):
                                    image_to_inject = link_cover(chapter['url'])

                                # Cross-reference: Match chapter title against episode game names
                                # Example: "Home Alone" chapter in OutRun episode gets Home Alone episode cover
                                elif chapter_title_lower in episode_titles_to_covers:
                                    image_to_inject = episode_titles_to_covers[chapter_title_lower]

                                # Exact suffix matching: Chapter ends with episode name
                                # Example: "Historien i Duke Nukem" → Duke Nukem episode
                                # Also normalize "the " prefix for better matching
                                # Example: "Oppsummering av Secret of Monkey Island" → "The Secret of Monkey Island"
                                # Only normalize if result has multiple words (to avoid "the games" → "games" false matches)
                                if not image_to_inject:
                                    for episode_name, cover in episode_titles_to_covers.items():
                                        if len(episode_name) <= 3:
                                            continue

                                        # Normalize episode name by removing "the " prefix
                                        # Only if result still has multiple words (contains space)
                                        episode_normalized = episode_name
                                        if episode_normalized.startswith("the "):
                                            without_the = episode_normalized[4:]
                                            if ' ' in without_the:  # Must have at least 2 words after removing "the"
                                                episode_normalized = without_the

                                        if ends_with_word(chapter_title_lower, episode_normalized):
                                            image_to_inject = cover
                                            break

                                # PREFIX matching: Chapter starts with episode name
                                # Example: "Doom II" → "Doom", "Transport Tycoon Deluxe" → "Transport Tycoon"
                                # Choose LONGEST matching prefix to avoid false matches
                                # (e.g., "Legend of Kyrandia" should match "the legend of kyrandia: hand of fate" not just "legend")
                                # Also normalize "the " prefix for better matching, but only strip it from
                                # the chapter when the episode name has it too
                                # (so "The Legend of Zelda" doesn't match "Legend")
                                if not image_to_inject:
                                    best_prefix_match = None
                                    best_prefix_length = 0

                                    for episode_name, cover in episode_titles_to_covers.items():
                                        if len(episode_name) <= 3:
                                            continue

                                        # Normalize both by removing "the " prefix
                                        episode_normalized = episode_name
                                        chapter_normalized = chapter_title_lower
                                        if episode_normalized.startswith("the "):
                                            episode_normalized = episode_normalized[4:]
                                            if chapter_normalized.startswith("the "):
                                                chapter_normalized = chapter_normalized[4:]

                                        # Check if chapter starts with episode name (using normalized versions)
                                        if starts_with_word(chapter_normalized, episode_normalized):
                                            # Keep the longest match (use normalized length for comparison)
                                            if len(episode_normalized) > best_prefix_length:
                                                best_prefix_match = cover
                                                best_prefix_length = len(episode_normalized)

                                    if best_prefix_match:
                                        image_to_inject = best_prefix_match

                                # Reverse PREFIX matching: Episode name starts with chapter
                                # Example: "Backpacker" → "Backpacker 2"
                                # Choose LONGEST matching episode name to avoid false matches
                                if not image_to_inject:
                                    best_reverse_match = None
                                    best_reverse_length = 0

                                    for episode_name, cover in episode_titles_to_covers.items():
                                        if len(chapter_title_lower) > 3 and starts_with_word(episode_name, chapter_title_lower):
                                            # Keep the longest episode name match
                                            if len(episode_name) > best_reverse_length:
                                                best_reverse_match = cover
                                                best_reverse_length = len(episode_name)

                                    if best_reverse_match:
                                        image_to_inject = best_reverse_match

                                # "I forhold til [game]" - cross-reference to that game's episode
                                if not image_to_inject and "i forhold til" in chapter_title_lower:
                                    game_name = chapter_title_lower.split("i forhold til", 1)[1].strip()
                                    if game_name in episode_titles_to_covers:
                                        image_to_inject = episode_titles_to_covers[game_name]

                                # "Ligner på [game]" - cross-reference to that game's episode
                                if not image_to_inject and "ligner på" in chapter_title_lower:
                                    game_name = chapter_title_lower.split("ligner på", 1)[1].strip()
                                    if game_name in episode_titles_to_covers:
                                        image_to_inject = episode_titles_to_covers[game_name]

                                # CONTAINS matching for "Mer [game]" pattern
                                # Example: "Mer Warcraft II" → contains "warcraft"
                                if not image_to_inject and chapter_title_lower.startswith("mer "):
                                    for episode_name, cover in episode_titles_to_covers.items():
                                        if len(episode_name) > 3 and episode_name in chapter_title_lower:
                                            image_to_inject = cover
                                            break

                                # "Kommentarer fra [episode]" - match episode name (not previous, not social media)
                                if not image_to_inject and chapter_title_lower.startswith("kommentarer fra "):
                                    # Skip if it's social media or previous episode (already handled above)
                                    if not any(x in chapter_title_lower for x in ["sosiale medier", "forrige", "sist", "facebook", "twitter", "bluesky"]):
                                        # Extract potential episode name
                                        potential_name = chapter_title_lower.replace("kommentarer fra ", "").strip()

                                        # Skip very short extracted names (≤3 chars) to avoid false matches
                                        # Example: "Kommentarer fra I" would incorrectly match "I Have No Mouth..."
                                        if len(potential_name) <= 3:
                                            continue

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

                                # Fuzzy word-based matching as last resort for multi-word titles
                                # Example: "Heroes of Might and Magic" → "Heroes of Might & Magic"
                                if not image_to_inject:
                                    chapter_words = normalize_words(chapter_title_lower)

                                    # Only apply to chapters with at least 3 words to avoid false positives
                                    if len(chapter_words) >= 3:
                                        best_match = None
                                        best_match_score = 0

                                        for episode_name, cover in episode_titles_to_covers.items():
                                            if len(episode_name) <= 3:
                                                continue

                                            episode_words = normalize_words(episode_name)
                                            common_words = chapter_words & episode_words
                                            match_score = len(common_words)

                                            # Strong match if most words overlap (at least 80% of chapter words)
                                            if len(chapter_words) > 0 and match_score >= len(chapter_words) * 0.8:
                                                if match_score > best_match_score:
                                                    best_match = cover
                                                    best_match_score = match_score

                                        if best_match:
                                            image_to_inject = best_match

                                # Inject the image
                                if image_to_inject:
                                    chapter['img'] = image_to_inject
                                    images_injected += 1

                                # Link to the matched episode in Apple Podcasts, unless the
                                # image is this episode's own cover or the podcast logo
                                if (image_to_inject and 'url' not in chapter
                                        and image_to_inject not in (cover_art_url, podcast_logo)
                                        and image_to_inject in cover_to_apple_url):
                                    chapter['url'] = cover_to_apple_url[image_to_inject]
                                    links_injected += 1
                            total_links += links_injected

                            # Clean up empty img and url fields before saving (both "" and null)
                            # This follows Podbean's practice of omitting the field entirely
                            for chapter in sorted_chapters:
                                for field in ('img', 'url'):
                                    if field in chapter and not chapter[field]:
                                        del chapter[field]

                            if output_dir:
                                # Save enriched JSON to output directory (for ALL episodes)
                                content = json.dumps(chapters_data, indent=2, ensure_ascii=False)
                                output_file = os.path.join(output_dir, filename)
                                with open(output_file, 'w', encoding='utf-8') as f:
                                    f.write(content)

                                # Update podcast:chapters URL to point to our hosted version (for ALL episodes).
                                # The content hash changes the URL only when the file changes, so clients
                                # that cache chapters by URL fetch the new version.
                                version = hashlib.sha256(content.encode('utf-8')).hexdigest()[:8]
                                new_url = f"{base_url}/{filename}?v={version}"
                                podcast_chapters.set('url', new_url)

                        if include_psc_tags:
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
                                    # Only add image if it has a non-empty value
                                    # (null or "" in source file disables auto-matching; cleaned up before PSC)
                                    if 'img' in chapter and chapter['img']:
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
                        else:
                            # URL rewrite + hosted JSON only; no PSC tags in output
                            converted_count += 1

                    except Exception:
                        failed_count += 1
                        # Silently skip episodes with failed chapter conversions
                        continue

        if include_psc_tags:
            print(f"✓ Converted {converted_count} JSON chapters to Podlove Simple Chapters format")
        else:
            print(f"✓ Hosted {converted_count} chapter JSON files and rewrote podcast:chapters URLs")
        if local_count > 0:
            print(f"  📁 {local_count} from local files (with toc: false support)")
        if apple_podcast_id:
            print(f"  🔗 {total_links} chapter links to other episodes in Apple Podcasts")
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

    def add_description_footer(
        self,
        social_links: List[Dict[str, str]],
        funding: Optional[Dict[str, str]] = None,
        episode_article_domain: Optional[str] = None,
        episode_article_text: str = "an article about the episode",
        episode_article_prefix: Optional[str] = None,
        discussion_text: Optional[str] = None,
        follow_text: str = "Follow us on",
        and_word: str = "and",
    ) -> 'FeedEnricher':
        """
        Append a standardized footer to episode descriptions.

        Adds an episode article link (derived from the item's <link> tag if it
        matches episode_article_domain), a link to the episode's Bluesky post
        (from item-level atproto podcast:socialInteract, so run
        add_bluesky_episode_social_interact first) and social/funding links to
        both <description> and <content:encoded>.

        Args:
            social_links: List of dicts with 'name' and 'url' keys
            funding: Optional dict with 'name', 'url', and 'text' keys
                     (text is the call-to-action, e.g. "Støtt oss gjerne på")
            episode_article_domain: Domain to match in <link> tag (e.g. "spillhistorie.no")
            episode_article_text: Anchor text for the article link
            episode_article_prefix: Text before the link (e.g. "Spillhistorie har skrevet")
            discussion_text: Text before the Bluesky post link (e.g. "Diskuter episoden på")
            follow_text: Text before the social links (e.g. "Følg oss gjerne på")
            and_word: Word before the last social link (e.g. "og")

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        items = self.channel.findall('item')
        article_count = 0
        discussion_count = 0
        footer_count = 0

        # Build social footer HTML
        social_parts = []
        if funding:
            social_parts.append(
                f"{funding['text']} <a href='{funding['url']}'>{funding['name']}</a>."
            )
        if social_links:
            names = []
            for i, link in enumerate(social_links):
                name_html = f"<a href='{link['url']}'>{link['name']}</a>"
                if i == len(social_links) - 1 and len(social_links) > 1:
                    names.append(f"{and_word} {name_html}")
                else:
                    names.append(name_html)
            social_parts.append(f"{follow_text} " + ", ".join(names) + ".")

        social_footer = "<br>\n".join(social_parts)

        for item in items:
            footer_parts = []

            # Check if <link> matches the article domain
            if episode_article_domain and episode_article_prefix:
                link_elem = item.find('link')
                if link_elem is not None and link_elem.text:
                    link_url = link_elem.text.strip()
                    if episode_article_domain in link_url:
                        footer_parts.append(
                            f"<p>{episode_article_prefix} "
                            f"<a href='{link_url}'>{episode_article_text}</a>.</p>"
                        )
                        article_count += 1

            if discussion_text:
                social = item.find(
                    '{https://podcastindex.org/namespace/1.0}socialInteract[@protocol="atproto"]'
                )
                if social is not None:
                    post_url = self.bluesky_post_url(social.get('uri'))
                    footer_parts.append(
                        f"<p>{discussion_text} <a href='{post_url}'>Bluesky</a>.</p>"
                    )
                    discussion_count += 1

            if social_footer:
                footer_parts.append(f"<p>{social_footer}</p>")

            if not footer_parts:
                continue

            footer_html = "\n".join(footer_parts)

            # Update <description>
            desc_elem = item.find('description')
            if desc_elem is not None and desc_elem.text:
                desc_elem.text = desc_elem.text.rstrip() + "\n\n" + footer_html

            # Update <content:encoded>
            content_elem = item.find('{http://purl.org/rss/1.0/modules/content/}encoded')
            if content_elem is not None and content_elem.text:
                content_elem.text = content_elem.text.rstrip() + "\n\n" + footer_html

            footer_count += 1

        print(f"✓ Added description footer to {footer_count} episodes "
              f"({article_count} with article links, {discussion_count} with Bluesky posts)")
        return self

    def trim_itunes_summary(self, min_length: int = 100) -> 'FeedEnricher':
        """
        Trim itunes:summary to the first paragraph of the description.

        Extracts the first <p> tag content from the description and uses it
        as itunes:summary. If the first paragraph is shorter than min_length,
        the second paragraph is appended.

        This ensures summaries are concise and consistent, without links,
        footer text, or other non-summary content.

        Args:
            min_length: Minimum character count for the summary. If the first
                        paragraph is shorter, the next paragraph is included.

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        from html.parser import HTMLParser

        class ParagraphExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.paragraphs = []
                self.current_text = ''
                self.in_p = False

            def handle_starttag(self, tag, attrs):
                if tag == 'p':
                    self.in_p = True
                    self.current_text = ''

            def handle_endtag(self, tag):
                if tag == 'p' and self.in_p:
                    text = self.current_text.strip()
                    if text:
                        self.paragraphs.append(text)
                    self.in_p = False

            def handle_data(self, data):
                if self.in_p:
                    self.current_text += data

            def handle_entityref(self, name):
                entities = {
                    'aring': 'å', 'oslash': 'ø', 'aelig': 'æ',
                    'Aring': 'Å', 'Oslash': 'Ø', 'Aelig': 'Æ',
                    'amp': '&', 'nbsp': ' ',
                }
                char = entities.get(name, f'&{name};')
                if self.in_p:
                    self.current_text += char

        itunes_ns = 'http://www.itunes.com/dtds/podcast-1.0.dtd'
        content_ns = 'http://purl.org/rss/1.0/modules/content/'
        items = self.channel.findall('item')
        updated_count = 0

        for item in items:
            summary_elem = item.find(f'{{{itunes_ns}}}summary')
            if summary_elem is None:
                continue

            # Get HTML description
            content_elem = item.find(f'{{{content_ns}}}encoded')
            desc_elem = item.find('description')
            html = ''
            if content_elem is not None and content_elem.text:
                html = content_elem.text
            elif desc_elem is not None and desc_elem.text:
                html = desc_elem.text

            if not html:
                continue

            # Extract paragraphs
            parser = ParagraphExtractor()
            parser.feed(html)

            if not parser.paragraphs:
                continue

            # Build summary from first paragraph, add second if too short
            summary = parser.paragraphs[0]
            if len(summary) < min_length and len(parser.paragraphs) > 1:
                summary = summary + ' ' + parser.paragraphs[1]

            old_summary = (summary_elem.text or '').strip()
            if old_summary != summary:
                summary_elem.text = summary
                updated_count += 1

        print(f"✓ Trimmed itunes:summary to first paragraph on {updated_count} episodes")
        return self

    def remove_itunes_summary(self, include_channel: bool = False) -> 'FeedEnricher':
        """
        Remove <itunes:summary> from items (and optionally the channel).

        Empirically verified that no tested client uses itunes:summary as its
        only source: MediaMonkey is the only one that prefers it, but falls
        back to <description> when absent. Item-level removal is safe for byte
        savings; channel-level is kept by default since it's a single element
        and some feed validators expect it.

        Args:
            include_channel: If True, also remove the channel-level
                <itunes:summary>

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        itunes_ns = 'http://www.itunes.com/dtds/podcast-1.0.dtd'
        removed = 0

        if include_channel:
            channel_summary = self.channel.find(f'{{{itunes_ns}}}summary')
            if channel_summary is not None:
                self.channel.remove(channel_summary)
                removed += 1

        for item in self.channel.findall('item'):
            summary = item.find(f'{{{itunes_ns}}}summary')
            if summary is not None:
                item.remove(summary)
                removed += 1

        print(f"✓ Removed {removed} itunes:summary element(s)")
        return self

    def remove_content_encoded(self) -> 'FeedEnricher':
        """
        Remove <content:encoded> from all items.

        All clients tested either use <description> as their primary or fall
        back to it when <content:encoded> is absent. Spotify's spec explicitly
        lists <description> (or media:description) as the required element.
        YouTube strips HTML from descriptions anyway.

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        content_ns = 'http://purl.org/rss/1.0/modules/content/'
        removed = 0

        for item in self.channel.findall('item'):
            content = item.find(f'{{{content_ns}}}encoded')
            if content is not None:
                item.remove(content)
                removed += 1

        print(f"✓ Removed {removed} content:encoded element(s)")
        return self

    def add_field_debug_markers(
        self,
        description_marker: str = "[DESC]",
        content_marker: str = "[CONT]",
        summary_marker: str = "[SUM]",
    ) -> 'FeedEnricher':
        """
        Append distinguishing markers to description, content:encoded, and itunes:summary.

        Useful for identifying which field each podcast client actually displays
        (they often contain nearly-identical text). Markers are appended at the
        very end to minimize visibility to regular listeners.

        Args:
            description_marker: Suffix for <description>
            content_marker: Suffix for <content:encoded>
            summary_marker: Suffix for <itunes:summary>

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        items = self.channel.findall('item')
        updated = 0

        for item in items:
            touched = False

            desc = item.find('description')
            if desc is not None and desc.text:
                desc.text = desc.text.rstrip() + f"\n\n{description_marker}"
                touched = True

            content = item.find('{http://purl.org/rss/1.0/modules/content/}encoded')
            if content is not None and content.text:
                content.text = content.text.rstrip() + f"\n\n{content_marker}"
                touched = True

            summary = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}summary')
            if summary is not None and summary.text:
                summary.text = summary.text.rstrip() + f" {summary_marker}"
                touched = True

            if touched:
                updated += 1

        print(f"✓ Added field debug markers to {updated} episodes")
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

    def remove_chapter_tags(
        self,
        remove_podcast: bool = True,
        remove_psc: bool = True,
    ) -> 'FeedEnricher':
        """
        Remove podcast:chapters and/or psc:chapters tags from episodes.

        Useful for variants that don't read one or both chapter formats:
          - YouTube: remove both (uses timestamps in descriptions instead)
          - Spotify: remove only podcast:chapters (reads psc:chapters inline)

        Args:
            remove_podcast: If True, remove <podcast:chapters> elements
            remove_psc: If True, remove <psc:chapters> elements

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
            if remove_podcast:
                podcast_chapters = item.find(f'{{{podcast_ns}}}chapters')
                if podcast_chapters is not None:
                    item.remove(podcast_chapters)
                    removed_podcast_chapters += 1

            if remove_psc:
                psc_chapters = item.find(f'{{{psc_ns}}}chapters')
                if psc_chapters is not None:
                    item.remove(psc_chapters)
                    removed_psc_chapters += 1

        parts = []
        if remove_podcast:
            parts.append(f"{removed_podcast_chapters} podcast:chapters")
        if remove_psc:
            parts.append(f"{removed_psc_chapters} psc:chapters")
        print(f"✓ Removed {' and '.join(parts)} tags")
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

    def update_lastBuildDate(self, timezone: str = "UTC") -> 'FeedEnricher':
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

        from datetime import datetime
        from email.utils import format_datetime
        from zoneinfo import ZoneInfo

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

    def shift_latest_episode_pubdate(self, hours: int = 6) -> 'FeedEnricher':
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

        from datetime import timedelta
        from email.utils import parsedate_to_datetime, format_datetime

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

    def write_feed(self, output_file: str) -> None:
        """
        Write enriched feed to file.

        Args:
            output_file: Output file path
        """
        super().write_feed(output_file)
        print(f"✓ Enriched feed written to: {output_file}")
