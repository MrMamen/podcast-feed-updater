"""Episode numbers in titles, and podcast:season / podcast:episode."""

import re
from typing import Callable, Optional, Self

from lxml import etree

from src.common.base_feed import BaseFeed
from src.common.namespaces import ITUNES, PODCAST


def itunes_episode_number(item) -> Optional[str]:
    """The item's itunes:episode, or None."""
    return (item.findtext(f'{ITUNES}episode') or '').strip() or None


class EpisodeNumbersMixin(BaseFeed):
    """FeedEnricher methods for episode numbers in titles, and podcast:season / podcast:episode."""

    def remove_episode_numbers_from_titles(self, pattern: str) -> Self:
        """
        Remove episode numbers from episode titles. A title that is nothing but
        the number ("Spillmatic #513") is kept as it is.

        Args:
            pattern: Regex matching the episode number, e.g. r'\\s*\\(#?\\d+\\)$' for "(#123)"

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        def without_number(title: str) -> str:
            return re.sub(pattern, '', title).strip() or title

        items = self.channel.findall('item')
        removed_count = 0

        for item in items:
            # Update <title>
            title_elem = item.find('title')
            if title_elem is not None and title_elem.text:
                new_title = without_number(title_elem.text)
                if new_title != title_elem.text:
                    title_elem.text = new_title
                    removed_count += 1

            # Also update <itunes:title> if present
            itunes_title = item.find(f'{ITUNES}title')
            if itunes_title is not None and itunes_title.text:
                itunes_title.text = without_number(itunes_title.text)

        print(f"✓ Removed episode numbers from {removed_count} episode titles")
        return self

    def add_podcast_season_episode(
        self,
        season_name: Optional[Callable[[int], str]] = None,
        episode_number: Callable[[etree._Element], Optional[str]] = itunes_episode_number,
    ) -> Self:
        """
        Add podcast:season and podcast:episode tags to all episodes, except
        where the source feed already has them.
        Uses itunes:season, and itunes:episode unless episode_number says otherwise.

        The podcast:episode tag includes a display attribute showing both
        the season episode number and total episode number (e.g., "2 (#80)").

        Args:
            season_name: Function from season number to the podcast:season name
                attribute (see podcast_utils.season_namer); None adds no name
            episode_number: Function from item to its episode number, or None

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        items = self.channel.findall('item')

        # First pass: count episodes per season (feed is in reverse chronological order)
        season_episode_counts = {}
        for item in items:
            season_elem = item.find(f'{ITUNES}season')
            if season_elem is not None and season_elem.text:
                season_num = int(season_elem.text)
                if season_num not in season_episode_counts:
                    season_episode_counts[season_num] = 0
                season_episode_counts[season_num] += 1

        # Second pass: add podcast:season and podcast:episode tags
        season_counters = {}
        added_count = 0

        kept_count = 0

        for item in items:
            season_elem = item.find(f'{ITUNES}season')
            episode_num_text = episode_number(item)
            has_season = item.find(f'{PODCAST}season') is not None
            has_episode = item.find(f'{PODCAST}episode') is not None
            kept_count += has_season or has_episode

            if season_elem is not None and season_elem.text:
                season_num = int(season_elem.text)

                # Add podcast:season
                podcast_season = etree.Element(f'{PODCAST}season')
                if season_name:
                    podcast_season.set('name', season_name(season_num))
                podcast_season.text = str(season_num)
                if not has_season:
                    item.append(podcast_season)

            if episode_num_text:
                total_episode_num = int(episode_num_text)

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
                        f'{PODCAST}episode',
                        display=display_value
                    )
                    podcast_episode.text = str(total_episode_num)
                    if not has_episode:
                        item.append(podcast_episode)
                else:
                    # No season info, just use total episode number
                    podcast_episode = etree.Element(
                        f'{PODCAST}episode'
                    )
                    podcast_episode.text = str(total_episode_num)
                    if not has_episode:
                        item.append(podcast_episode)

            if season_elem is not None or episode_num_text:
                added_count += 1

        print(f"✓ Added podcast:season and podcast:episode tags to {added_count} episodes")
        if kept_count:
            print(f"  ℹ️  Kept the source feed's own tags on {kept_count} episodes")
        return self

    def restore_episode_numbers_to_titles(
        self,
        format: str = ' (#{episode})',
        has_number: Optional[Callable[[str], bool]] = None,
    ) -> Self:
        """
        Put episode numbers back into the titles, from podcast:episode (or
        itunes:episode). Inverse of remove_episode_numbers_from_titles(), for
        destinations like YouTube that show no episode number otherwise. Skips
        bonus episodes (episodeType=bonus).

        Args:
            format: Appended to the title, with {episode} for the number
                (' (#{episode})'), or the whole title if it contains {title}
                ('#{episode} – {title}')
            has_number: Titles for which this returns True already show their
                number and are left alone

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        def numbered(title: str, number: str) -> str:
            if has_number and has_number(title):
                return title
            if '{title}' in format:
                return format.format(title=title, episode=number)
            suffix = format.format(episode=number)
            return title if suffix in title else title + suffix  # Avoid duplicates

        items = self.channel.findall('item')
        restored_count = 0
        skipped_bonus = 0

        for item in items:
            if item.findtext(f'{ITUNES}episodeType') == 'bonus':
                skipped_bonus += 1
                continue

            number = (item.findtext(f'{PODCAST}episode') or '').strip() or itunes_episode_number(item)
            if not number:
                continue

            title_elem = item.find('title')
            if title_elem is not None and title_elem.text:
                new_title = numbered(title_elem.text, number)
                if new_title != title_elem.text:
                    title_elem.text = new_title
                    restored_count += 1

            itunes_title = item.find(f'{ITUNES}title')
            if itunes_title is not None and itunes_title.text:
                itunes_title.text = numbered(itunes_title.text, number)

        print(f"✓ Restored episode numbers to {restored_count} episode titles (skipped {skipped_bonus} bonus episodes)")
        return self
