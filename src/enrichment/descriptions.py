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
