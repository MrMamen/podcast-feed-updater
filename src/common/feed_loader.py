"""Shared helpers for loading the cd SPILL feed."""

from __future__ import annotations

import sys
from pathlib import Path

import requests

FEED_URL = "https://feed.podbean.com/cdspill/feed.xml"
CACHE_PATH = Path(".cache/cdspill-original.xml")

PUBLISH_BASE_URL = "https://mrmamen.github.io/podcast-feed-updater"
ENRICHED_FEED_URL = f"{PUBLISH_BASE_URL}/cdspill-enriched.xml"
ENRICHED_LOCAL_PATH = Path("output/cdspill-enriched.xml")

CACHE_HINT = "   Kjør først: uv run analyze.py cache   (eller: uv run guests.py cache)"


def download_cache(cache_path: Path = CACHE_PATH, url: str = FEED_URL, quiet: bool = False) -> Path:
    """Download the original feed to ``cache_path`` and return the path."""
    if not quiet:
        print(f"📡 Henter feed fra {url}...")
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(response.content)
    if not quiet:
        print(f"✓ Lagret {len(response.content) / 1024:.1f} KB til {cache_path}")
    return cache_path


def load_feed(
    *,
    use_cache: bool = True,
    cache_path: Path = CACHE_PATH,
    url: str = FEED_URL,
    quiet: bool = False,
    auto_download: bool = False,
) -> str:
    """
    Return the cd SPILL feed XML as a string.

    When ``use_cache`` is True (default), reads from the local cache file.
    If the cache is missing, the function exits with a helpful error unless
    ``auto_download`` is set, in which case it downloads the cache first.
    Set ``use_cache=False`` to fetch from the live feed URL.
    """
    if use_cache:
        if not cache_path.exists():
            if auto_download:
                download_cache(cache_path, url, quiet=quiet)
            else:
                print(f"❌ Fant ikke lokal cache på {cache_path}")
                print(CACHE_HINT)
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
            print(CACHE_HINT)
            sys.exit(1)
        return str(cache_path)
    return url


def resolve_enriched_source(use_local: bool) -> str:
    """
    Source for the derived feeds (Spotify / YouTube / fallback-test) that build
    on the already enriched feed: the local ``output/`` copy when ``use_local``
    is set, otherwise the published GitHub Pages URL. Exits if the local copy
    is requested but missing.
    """
    if use_local:
        if not ENRICHED_LOCAL_PATH.exists():
            print(f"\n❌ Error: Enriched feed not found at {ENRICHED_LOCAL_PATH}")
            print("   Run enrich_cdspill.py first to generate the enriched feed")
            sys.exit(1)
        print(f"\n📁 Using local enriched feed: {ENRICHED_LOCAL_PATH}")
        return str(ENRICHED_LOCAL_PATH)
    print(f"\n🌐 Fetching enriched feed from: {ENRICHED_FEED_URL}")
    return ENRICHED_FEED_URL
