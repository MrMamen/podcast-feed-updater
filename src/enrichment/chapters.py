"""Chapters: hosted JSON with images and links, psc:chapters, and timestamps for YouTube."""

import hashlib
import json
import os
import shutil
from typing import Dict, List, Optional, Self
from urllib.parse import urlparse

import requests
from lxml import etree

from src.common.base_feed import BaseFeed
from src.common.http import USER_AGENT
from src.common.podcast_utils import TitleRules
from src.enrichment.chapter_images import (
    EPISODE_COVER,
    NEXT_COVER,
    PODCAST_LOGO,
    PREVIOUS_COVER,
    ChapterImageMatcher,
)


class ChaptersMixin(BaseFeed):
    """FeedEnricher methods for chapters: hosted JSON with images and links, psc:chapters, and timestamps for YouTube."""

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
        image_rules: Optional[List[Dict]] = None,
        cross_references: Optional[List[Dict]] = None,
    ) -> Self:
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
                output_dir/images and published at base_url/images
            include_psc_tags: If True, insert <psc:chapters> inline (for Spotify variant).
                If False, only host JSON and rewrite URLs (for main feed).
            apple_podcast_id: If set, chapters whose image refers to another episode
                also get a "url" to that episode in Apple Podcasts. A "url" already in
                the chapter file is kept; "url": null disables the automatic link.
            apple_country: Apple Podcasts storefront for those links (e.g. "no")
            title_rules: Title conventions, so chapters can be matched against what
                other episodes are about ("Rainbow Six med Jostein" → "Rainbow Six")
            image_rules, cross_references: Podcast-specific rules for chapter images,
                see chapter_images.ChapterImageMatcher

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

        matcher = ChapterImageMatcher(
            episode_titles_to_covers,
            image_rules=image_rules,
            cross_references=cross_references,
            images_base_url=f"{base_url}/images" if images_dir else None,
            link_cover=link_cover,
        )

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
                                # Skip if chapter already has an image (including null to disable auto-matching)
                                # You can use "img": null in chapter file to prevent auto-matching
                                # (empty/null values are cleaned up before saving output)
                                if 'img' in chapter:
                                    continue

                                image_to_inject = matcher.image_for(chapter, {
                                    EPISODE_COVER: cover_art_url,
                                    PREVIOUS_COVER: prev_cover_url,
                                    NEXT_COVER: next_cover_url,
                                    PODCAST_LOGO: podcast_logo,
                                })

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

                                    etree.SubElement(
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

    def add_chapter_timestamps_to_description(self, separator: str = '\n\n') -> Self:
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
    ) -> Self:
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
