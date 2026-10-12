#!/usr/bin/env python3
"""
Tell Podcast Index that a published feed has changed (hub/pubnotify), so it
re-crawls right away instead of on its own polling schedule.

Run after the gh-pages deploy:

    uv run --no-dev pubnotify.py output/cdspill-enriched.xml \\
        --url https://mrmamen.github.io/podcast-feed-updater/cdspill-enriched.xml \\
        --previous previous.xml

Skips the notify when the feed is unchanged apart from lastBuildDate (compared
against --previous, the live feed fetched before the deploy). Otherwise it
waits until GitHub Pages actually serves the new build, so Podcast Index
doesn't fetch the old one. No API key needed; the endpoint only requires an
identifying User-Agent.
"""

import argparse
import re
import sys
import time

import requests

PUBNOTIFY_URL = "https://api.podcastindex.org/api/1.0/hub/pubnotify"
USER_AGENT = "cdspill-feed-updater/1.0 (+https://github.com/MrMamen/podcast-feed-updater)"
LAST_BUILD_RE = re.compile(r"<lastBuildDate>([^<]*)</lastBuildDate>")


def last_build_date(xml: str) -> str | None:
    match = LAST_BUILD_RE.search(xml)
    return match.group(1) if match else None


def without_last_build_date(xml: str) -> str:
    return LAST_BUILD_RE.sub("", xml)


def wait_until_live(url: str, expected: str, timeout: int, interval: int) -> bool:
    """Poll url until it serves the build with lastBuildDate == expected."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            # Query string bypasses the Pages CDN cache (max-age=600)
            resp = requests.get(
                url,
                params={"cb": int(time.time())},
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )
            live = last_build_date(resp.text) if resp.ok else None
        except requests.RequestException as exc:
            live = None
            print(f"  fetch failed: {exc}")
        if live == expected:
            return True
        if time.monotonic() >= deadline:
            print(f"  still serving lastBuildDate {live!r}, expected {expected!r}")
            return False
        print(f"  not live yet ({live}), retrying in {interval} s")
        time.sleep(interval)


def pubnotify(url: str) -> bool:
    resp = requests.get(
        PUBNOTIFY_URL,
        params={"url": url},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    print(f"  HTTP {resp.status_code}: {resp.text.strip()}")
    try:
        return resp.ok and str(resp.json().get("status")).lower() == "true"
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("feed", help="local feed file that was just deployed")
    parser.add_argument("--url", required=True, help="public URL of the feed")
    parser.add_argument(
        "--previous", help="live feed fetched before the deploy; unchanged feed skips notify"
    )
    parser.add_argument("--force", action="store_true", help="notify even if unchanged")
    parser.add_argument("--timeout", type=int, default=600, help="seconds to wait for Pages")
    parser.add_argument("--interval", type=int, default=20)
    args = parser.parse_args()

    with open(args.feed, encoding="utf-8") as f:
        new = f.read()

    if args.previous and not args.force:
        try:
            with open(args.previous, encoding="utf-8") as f:
                old = f.read()
        except FileNotFoundError:
            old = None
        if old is not None and without_last_build_date(old) == without_last_build_date(new):
            print("Feed unchanged apart from lastBuildDate, skipping pubnotify")
            return 0

    expected = last_build_date(new)
    if expected is None:
        print("No lastBuildDate in local feed, can't tell when Pages is live")
        return 1

    print(f"Waiting for {args.url} to serve lastBuildDate {expected}")
    if not wait_until_live(args.url, expected, args.timeout, args.interval):
        return 1

    print(f"Notifying Podcast Index: {args.url}")
    return 0 if pubnotify(args.url) else 1


if __name__ == "__main__":
    sys.exit(main())
