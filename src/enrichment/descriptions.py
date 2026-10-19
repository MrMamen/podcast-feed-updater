"""Episode descriptions: footer, and the redundant description-like fields."""

from typing import Dict, List, Optional, Self

from src.common.base_feed import BaseFeed


class DescriptionsMixin(BaseFeed):
    """FeedEnricher methods for episode descriptions: footer, and the redundant description-like fields."""

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
    ) -> Self:
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

    def trim_itunes_summary(self, min_length: int = 100) -> Self:
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

    def remove_itunes_summary(self, include_channel: bool = False) -> Self:
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

    def remove_content_encoded(self) -> Self:
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
    ) -> Self:
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
