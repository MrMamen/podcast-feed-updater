"""Chapters: hosted JSON with images and links, psc:chapters, and timestamps for YouTube."""

import hashlib
import json
import os
import re
import shutil
from typing import Dict, List, Optional, Self
from urllib.parse import unquote, urlparse

import requests
from lxml import etree

from src.common.base_feed import BaseFeed
from src.common.http import USER_AGENT
from src.common.namespaces import CONTENT, ITUNES, PODCAST, PSC, PSC_NS
from src.common.podcast_utils import TitleRules
from src.enrichment.chapter_images import (
    EPISODE_COVER,
    NEXT_COVER,
    PODCAST_LOGO,
    PREVIOUS_COVER,
    ChapterImageMatcher,
    normalize_title,
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
        hosted_dir: Optional[str] = None,
        images_dir: Optional[str] = None,
        include_psc_tags: bool = True,
        apple_podcast_id: Optional[int] = None,
        apple_country: str = "us",
        title_rules: Optional[TitleRules] = None,
        image_rules: Optional[List[Dict]] = None,
        cross_references: Optional[List[Dict]] = None,
        match_other_episodes: bool = False,
    ) -> Self:
        """
        Process the chapter JSON of every episode and optionally add Podlove
        Simple Chapters (PSC) tags.

        For each episode with a podcast:chapters JSON: load it (a file with the
        same name in chapters_dir takes precedence over the source feed's), sort
        it, add an intro chapter at 00:00 if missing, add images and links (see
        chapter_images.ChapterImageMatcher), drop hidden chapters left without
        either, and with output_dir save it there
        and point podcast:chapters at the hosted copy. With include_psc_tags,
        also insert the visible chapters as <psc:chapters> (Spotify).

        Chapter files support "toc": false (hidden from the table of contents),
        and "img": null / "url": null to disable the automatic image or link.

        Args:
            base_url: Public URL that output_dir is published at
            chapters_dir: Directory containing local chapter JSON files, named like the
                files in the source feed; they take precedence over the source's
            output_dir: Directory to copy chapter files to for hosting. None skips hosting
                and leaves podcast:chapters URLs as they are, so variant feeds don't
                overwrite the chapter files the main feed publishes.
            hosted_dir: Where the main feed wrote its hosted copies. Variants built from a
                local enriched feed read them from here, since its podcast:chapters URLs
                point to files that aren't published yet.
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
            image_rules, cross_references, match_other_episodes: Podcast-specific rules
                for chapter images, see chapter_images.ChapterImageMatcher

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        if include_psc_tags:
            self._ensure_namespace('psc', PSC_NS)

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            if images_dir:
                shutil.copytree(images_dir, os.path.join(output_dir, 'images'), dirs_exist_ok=True)

        channel_image = self.channel.find(f'{ITUNES}image')
        podcast_logo = channel_image.get('href') if channel_image is not None else None

        items = self.channel.findall('item')
        apple_urls = (self._fetch_apple_episode_urls(apple_podcast_id, apple_country)
                      if apple_podcast_id else {})
        episode_covers, subject_covers, cover_to_apple_url = self._index_episode_covers(
            items, title_rules or TitleRules(), apple_urls
        )

        # Chapter link -> cover image, so a link used in several chapters is looked up once
        link_covers = {}

        def link_cover(url):
            if url not in link_covers:
                link_covers[url] = self._fetch_link_cover(url)
            return link_covers[url]

        matcher = ChapterImageMatcher(
            subject_covers,
            image_rules=image_rules,
            cross_references=cross_references,
            images_base_url=f"{base_url}/images" if images_dir else None,
            link_cover=link_cover,
            match_other_episodes=match_other_episodes,
        )

        converted_count = failed_count = local_count = total_links = total_dropped = 0
        used_local_files = set()

        for item_index, item in enumerate(items):
            podcast_chapters = item.find(f'{PODCAST}chapters')
            json_url = podcast_chapters.get('url') if podcast_chapters is not None else None
            if not json_url or not urlparse(json_url).path.endswith('.json'):
                continue
            # e.g. "Outrun_chapters.json"
            filename = os.path.basename(urlparse(json_url).path)
            episode_title = item.findtext('title') or 'Unknown'

            try:
                chapters_data = self._load_chapter_file(
                    json_url, os.path.join(chapters_dir, filename), episode_title
                )
                is_local = chapters_data is not None
                hosted_file = os.path.join(hosted_dir, filename) if hosted_dir else None
                if is_local:
                    local_count += 1
                    used_local_files.add(filename)
                elif hosted_file and os.path.exists(hosted_file):
                    with open(hosted_file, 'r', encoding='utf-8') as f:
                        chapters_data = json.load(f)
                else:
                    response = requests.get(json_url, timeout=10)
                    response.raise_for_status()
                    chapters_data = response.json()

                if 'chapters' in chapters_data:
                    chapters = self._sorted_with_intro(
                        chapters_data['chapters'], episode_title,
                        "local file" if is_local else json_url, json_url,
                    )
                    chapters_data['chapters'] = chapters
                    total_links += self._add_images_and_links(chapters, matcher, cover_to_apple_url, {
                        EPISODE_COVER: episode_covers[item_index],
                        PREVIOUS_COVER: (episode_covers[item_index + 1]
                                         if item_index + 1 < len(episode_covers) else None),
                        NEXT_COVER: episode_covers[item_index - 1] if item_index > 0 else None,
                        PODCAST_LOGO: podcast_logo,
                    })
                    total_dropped += self._drop_empty_hidden_chapters(chapters)
                    if output_dir:
                        podcast_chapters.set(
                            'url', self._host_chapter_file(chapters_data, output_dir, filename, base_url)
                        )

                if not include_psc_tags:
                    converted_count += 1
                elif 'chapters' in chapters_data:
                    self._insert_psc_chapters(item, podcast_chapters, chapters_data['chapters'])
                    converted_count += 1

            except Exception as e:
                failed_count += 1
                print(f"  ⚠️  Could not process chapters for {episode_title}: {e}")

        if include_psc_tags:
            print(f"✓ Converted {converted_count} JSON chapters to Podlove Simple Chapters format")
        else:
            print(f"✓ Hosted {converted_count} chapter JSON files and rewrote podcast:chapters URLs")
        if local_count > 0:
            print(f"  📁 {local_count} from local files (with toc: false support)")
        if apple_podcast_id:
            print(f"  🔗 {total_links} chapter links to other episodes in Apple Podcasts")
        if total_dropped > 0:
            print(f"  🗑️  Dropped {total_dropped} hidden chapters with neither image nor link")
        if failed_count > 0:
            print(f"  ⚠ {failed_count} episodes failed to convert")

        if os.path.isdir(chapters_dir):
            unused_files = {
                f for f in os.listdir(chapters_dir) if f.endswith('.json') and not f.startswith('.')
            } - used_local_files
            if unused_files:
                print(f"  ⚠️  Found {len(unused_files)} unused chapter file(s) in {chapters_dir}/")
                for filename in sorted(unused_files):
                    print(f"      - {filename} (check filename matches the source feed's URL)")

        return self

    @staticmethod
    def _index_episode_covers(items: list, title_rules: TitleRules, apple_urls: Dict[str, str]):
        """
        Returns ``(episode_covers, subject_covers, cover_to_apple_url)``:

        - each item's cover URL, in feed order (for previous/next episode covers)
        - what each episode is about → its cover, normalized for matching
          ("Rainbow Six med Jostein Hakestad" → "rainbow six"; "Rainbow Six:
          Rogue Spear" also as "rainbow six")
        - cover → Apple Podcasts URL, for linking chapters that show another
          episode's cover. Covers shared by several episodes are ambiguous and
          get no link.
        """
        episode_covers = []
        subject_covers = {}
        cover_to_apple_url = {}
        ambiguous_covers = set()

        for item in items:
            itunes_image = item.find(f'{ITUNES}image')
            cover_url = itunes_image.get('href') if itunes_image is not None else None
            episode_covers.append(cover_url)
            if not cover_url:
                continue

            apple_url = apple_urls.get(item.findtext('guid'))
            if cover_url in cover_to_apple_url or cover_url in ambiguous_covers:
                ambiguous_covers.add(cover_url)
                cover_to_apple_url.pop(cover_url, None)
            elif apple_url:
                cover_to_apple_url[cover_url] = apple_url

            title_elem = item.find('title')
            if title_elem is not None:
                subject = normalize_title(title_rules.subject(title_elem.text))
                subject_covers[subject] = cover_url
                if ':' in subject:
                    subject_covers[subject.split(':')[0].strip()] = cover_url

        return episode_covers, subject_covers, cover_to_apple_url

    @staticmethod
    def _load_chapter_file(json_url: str, local_file: str, episode_title: str) -> Optional[Dict]:
        """
        The local chapter file, or None if there is none (or it is invalid).
        Warns when it has a different number of chapters than the source's copy.
        """
        if not os.path.exists(local_file):
            return None
        try:
            with open(local_file, 'r', encoding='utf-8') as f:
                chapters_data = json.load(f)
        except Exception as e:
            print(f"  ⚠️  Failed to load local file {os.path.basename(local_file)}: {e}")
            return None

        try:
            response = requests.get(json_url, timeout=10)
            response.raise_for_status()
            source_count = len(response.json().get('chapters', []))
        except Exception:
            return chapters_data  # The comparison is only a hint
        local_count = len(chapters_data.get('chapters', []))
        if local_count != source_count:
            print(f"  ⚠️  Chapter count mismatch: {episode_title}")
            print(f"      Local file:  {local_count} chapters ({os.path.basename(local_file)})")
            print(f"      Source feed: {source_count} chapters")
            print("      Check if the local file needs updating")
        return chapters_data

    @staticmethod
    def _sorted_with_intro(chapters: List[Dict], episode_title: str, source_label: str,
                           json_url: str) -> List[Dict]:
        """Chapters sorted by startTime, with an "Intro" at 00:00 if the first visible one starts later."""
        if any(a.get('startTime', 0) > b.get('startTime', 0) for a, b in zip(chapters, chapters[1:])):
            print(f"  ⚠️  Unsorted chapters detected: {episode_title}")
            print(f"      Source: {source_label}")
        chapters = sorted(chapters, key=lambda ch: ch.get('startTime', 0))

        visible = [ch for ch in chapters if ch.get('toc', True)]
        if visible and visible[0].get('startTime', 0) > 0:
            print(f"  ⚠️  Missing 00:00 intro chapter: {episode_title}")
            print(f"      Source JSON: {json_url}")
            chapters.insert(0, {'startTime': 0, 'title': 'Intro'})
        return chapters

    @staticmethod
    def _add_images_and_links(chapters: List[Dict], matcher: ChapterImageMatcher,
                              cover_to_apple_url: Dict[str, str], covers: Dict) -> int:
        """
        Give chapters without "img" an image, and those showing another episode's
        cover a "url" to it in Apple Podcasts. Then drops empty "img"/"url"
        values (null disables the automatic one). Returns the number of links added.
        """
        links_added = 0
        for chapter in chapters:
            if 'img' in chapter:
                continue
            image = matcher.image_for(chapter, covers)
            if not image:
                continue
            chapter['img'] = image
            # Not for this episode's own cover or the podcast logo
            if ('url' not in chapter and image not in (covers[EPISODE_COVER], covers[PODCAST_LOGO])
                    and image in cover_to_apple_url):
                chapter['url'] = cover_to_apple_url[image]
                links_added += 1

        for chapter in chapters:
            for field in ('img', 'url'):
                if field in chapter and not chapter[field]:
                    del chapter[field]
        return links_added

    @staticmethod
    def _drop_empty_hidden_chapters(chapters: List[Dict]) -> int:
        """
        Remove "toc": false chapters that still have neither "img" nor "url"
        after images and links are added. They exist to show an image embedded
        in the MP3's ID3 tags, which the JSON can't carry, so without one they
        only make apps without image inheritance fall back to the episode cover.
        Returns the number removed.
        """
        kept = [ch for ch in chapters
                if ch.get('toc', True) is not False or 'img' in ch or 'url' in ch]
        dropped = len(chapters) - len(kept)
        chapters[:] = kept
        return dropped

    @staticmethod
    def _host_chapter_file(chapters_data: Dict, output_dir: str, filename: str, base_url: str) -> str:
        """
        Write the chapter file to output_dir and return its public URL. The
        content hash in the URL changes only when the file does, so clients that
        cache chapters by URL fetch the new version.
        """
        content = json.dumps(chapters_data, indent=2, ensure_ascii=False)
        with open(os.path.join(output_dir, filename), 'w', encoding='utf-8') as f:
            f.write(content)
        version = hashlib.sha256(content.encode('utf-8')).hexdigest()[:8]
        return f"{base_url}/{filename}?v={version}"

    def _insert_psc_chapters(self, item, podcast_chapters, chapters: List[Dict]) -> None:
        """Insert the visible chapters as <psc:chapters> right after podcast:chapters."""
        psc_chapters = etree.Element(f'{PSC}chapters', version="1.2")
        for chapter in chapters:
            if chapter.get('toc', True) is False:
                continue
            start_time = chapter.get('startTime', 0)
            attrs = {
                'start': (f"{int(start_time // 3600):02d}:{int((start_time % 3600) // 60):02d}:"
                          f"{int(start_time % 60):02d}"),
                'title': chapter.get('title', ''),
            }
            if 'url' in chapter:
                attrs['href'] = chapter['url']
            if chapter.get('img'):
                attrs['image'] = chapter['img']
            etree.SubElement(psc_chapters, f'{PSC}chapter', **attrs)

        item.insert(list(item).index(podcast_chapters) + 1, psc_chapters)
        self._add_newline_before_element(item, psc_chapters)

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

        items = self.channel.findall('item')
        updated_count = 0

        for item in items:
            # Find psc:chapters element (must be present from convert_json_chapters_to_psc)
            psc_chapters = item.find(f'{PSC}chapters')
            if psc_chapters is None:
                continue

            # Extract all chapter elements
            chapters = psc_chapters.findall(f'{PSC}chapter')
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
            content_elem = item.find(f'{CONTENT}encoded')
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

        items = self.channel.findall('item')

        removed_podcast_chapters = 0
        removed_psc_chapters = 0

        for item in items:
            if remove_podcast:
                podcast_chapters = item.find(f'{PODCAST}chapters')
                if podcast_chapters is not None:
                    item.remove(podcast_chapters)
                    removed_podcast_chapters += 1

            if remove_psc:
                psc_chapters = item.find(f'{PSC}chapters')
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
