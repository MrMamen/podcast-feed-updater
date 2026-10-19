"""Episode numbers in titles, and podcast:season / podcast:episode."""

from typing import Callable, Optional, Self

from lxml import etree

from src.common.base_feed import BaseFeed
from src.common.podcast_utils import DEFAULT_EPISODE_NUMBER_SUFFIX


class EpisodeNumbersMixin(BaseFeed):
    """FeedEnricher methods for episode numbers in titles, and podcast:season / podcast:episode."""

    def remove_episode_numbers_from_titles(
        self, pattern: str = DEFAULT_EPISODE_NUMBER_SUFFIX
    ) -> Self:
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

    def add_podcast_season_episode(
        self, season_name: Optional[Callable[[int], str]] = None
    ) -> Self:
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

    def restore_episode_numbers_to_titles(self, format: str = ' (#{episode})') -> Self:
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
