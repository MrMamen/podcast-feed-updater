"""podcast:transcript: language attribute and versioned URLs."""

from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Self
from urllib.parse import urlparse

import requests

from src.common.base_feed import BaseFeed
from src.common.http import USER_AGENT


class TranscriptsMixin(BaseFeed):
    """FeedEnricher methods for podcast:transcript: language attribute and versioned URLs."""

    def add_language_to_transcripts(
        self,
        default_language: str = "no",
        overrides: dict[str, str] | None = None,
    ) -> Self:
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

    def add_transcript_versions(self, workers: int = 8) -> Self:
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
