"""Shared helpers for loading a podcast's source feed and its enriched feed."""

from __future__ import annotations

import sys
from pathlib import Path

import requests

from src.config import PodcastConfig

CACHE_HINT = "   Kjør først: uv run analyze.py cache   (eller: uv run guests.py cache)"


def download_cache(cfg: PodcastConfig, quiet: bool = False) -> Path:
    """Download the source feed to the podcast's cache path and return the path."""
    url, cache_path = cfg.source_feed, cfg.cache_path
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
    cfg: PodcastConfig,
    *,
    use_cache: bool = True,
    quiet: bool = False,
    auto_download: bool = False,
) -> str:
    """
    Return the podcast's source feed XML as a string.

    When ``use_cache`` is True (default), reads from the local cache file.
    If the cache is missing, the function exits with a helpful error unless
    ``auto_download`` is set, in which case it downloads the cache first.
    Set ``use_cache=False`` to fetch from the live feed URL.
    """
    cache_path = cfg.cache_path
    if use_cache:
        if not cache_path.exists():
            if auto_download:
                download_cache(cfg, quiet=quiet)
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
        print(f"📡 Henter feed fra {cfg.source_feed}...")
    response = requests.get(cfg.source_feed, timeout=30)
    response.raise_for_status()
    if not quiet:
        print("✓ Feed hentet")
    return response.text


def resolve_feed_source(cfg: PodcastConfig, use_cache: bool) -> str:
    """
    Return a source identifier usable by ``BaseFeed.fetch_feed()``.

    Returns the cache path as a string if ``use_cache`` is True (and the
    cache exists), otherwise the live feed URL. Exits if the cache is
    requested but missing.
    """
    if use_cache:
        if not cfg.cache_path.exists():
            print(f"❌ Fant ikke lokal cache på {cfg.cache_path}")
            print(CACHE_HINT)
            sys.exit(1)
        return str(cfg.cache_path)
    return cfg.source_feed


def resolve_enriched_source(cfg: PodcastConfig, use_local: bool) -> str:
    """
    Source for the variant feeds (Spotify / YouTube / fallback-test) that build
    on the already enriched feed: the local ``output/`` copy when ``use_local``
    is set, otherwise the published URL. Exits if the local copy is requested
    but missing.
    """
    local_path = cfg.enriched_local_path
    if use_local:
        if not local_path.exists():
            print(f"\n❌ Error: Enriched feed not found at {local_path}")
            print(f"   Run 'uv run enrich.py --podcast {cfg.id}' first to generate the enriched feed")
            sys.exit(1)
        print(f"\n📁 Using local enriched feed: {local_path}")
        return str(local_path)
    print(f"\n🌐 Fetching enriched feed from: {cfg.feed_url}")
    return cfg.feed_url
