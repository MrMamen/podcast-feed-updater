"""podcast:socialInteract, including per-episode Bluesky posts."""

from typing import Optional, Self

import requests
from lxml import etree

from src.common.base_feed import BaseFeed


class SocialMixin(BaseFeed):
    """FeedEnricher methods for podcast:socialInteract, including per-episode Bluesky posts."""

    def add_social_interact(
        self,
        protocol: str,
        uri: str,
        account_id: Optional[str] = None,
        account_url: Optional[str] = None,
        priority: Optional[int] = None
    ) -> Self:
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
    ) -> Self:
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
