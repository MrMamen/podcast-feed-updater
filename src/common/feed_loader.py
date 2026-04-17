"""Shared helpers for loading the cd SPILL feed."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import requests

FEED_URL = "https://feed.podbean.com/cdspill/feed.xml"
CACHE_PATH = Path(".cache/cdspill-original.xml")


def load_feed(
    *,
    use_cache: bool = True,
    cache_path: Path = CACHE_PATH,
    url: str = FEED_URL,
    quiet: bool = False,
) -> str:
    """
    Return the cd SPILL feed XML as a string.

    When ``use_cache`` is True (default), reads from the local cache file.
    If the cache is missing, the function exits with a helpful error instead
    of silently falling back to the network. Set ``use_cache=False`` to fetch
    from the live feed URL.
    """
    if use_cache:
        if not cache_path.exists():
            print(f"❌ Fant ikke lokal cache på {cache_path}")
            print("   Kjør først: uv run python3 scripts/download_cdspill_cache.py")
            sys.exit(1)
        if not quiet:
            print(f"📂 Leser feed fra {cache_path}...")
        text = cache_path.read_text(encoding="utf-8")
        if not quiet:
            print("✓ Feed lastet")
        return text

    if not quiet:
        print(f"📡 Henter feed fra {url}...")
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    if not quiet:
        print("✓ Feed hentet")
    return response.text


def resolve_feed_source(use_cache: bool, cache_path: Path = CACHE_PATH, url: str = FEED_URL) -> str:
    """
    Return a source identifier usable by ``BaseFeed.fetch_feed()``.

    Returns the cache path as a string if ``use_cache`` is True (and the
    cache exists), otherwise the live feed URL. Exits if the cache is
    requested but missing.
    """
    if use_cache:
        if not cache_path.exists():
            print(f"❌ Fant ikke lokal cache på {cache_path}")
            print("   Kjør først: uv run python3 scripts/download_cdspill_cache.py")
            sys.exit(1)
        return str(cache_path)
    return url
