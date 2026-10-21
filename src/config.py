"""
Per-podcast configuration, read from ``podcasts/<id>/podcast.toml``, and the
list feed configuration in ``podcasts/<id>/list.toml``.

Everything that is specific to one podcast (feed URLs, guid, funding, social
accounts, title conventions, chapter rules, variants) lives in that file, so
the code under ``src/`` stays generic. Relative paths in the file are relative
to the podcast's directory. See docs/CONFIGURATION.md for all options.
"""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.common.podcast_utils import TitleRules

PODCASTS_DIR = Path("podcasts")
CONFIG_NAME = "podcast.toml"
LIST_CONFIG_NAME = "list.toml"
OUTPUT_DIR = Path("output")
CACHE_DIR = Path(".cache")

# Top-level sections podcast.toml may contain; anything else is a typo.
KNOWN_SECTIONS = {
    "podcast", "publish", "titles", "seasons", "guests", "funding", "update_frequency",
    "podroll", "social_interact", "bluesky", "description_footer", "transcripts",
    "chapters", "variants",
}
KNOWN_VARIANTS = {"youtube", "spotify", "fallback-test"}


class ConfigError(Exception):
    """Raised when podcast.toml is missing, invalid or incomplete."""


class PodcastConfig:
    """Parsed podcast.toml plus the paths and URLs derived from it."""

    def __init__(self, podcast_id: str, data: Dict[str, Any], directory: Path):
        self.id = podcast_id
        self.data = data
        self.dir = directory

        unknown = set(data) - KNOWN_SECTIONS
        if unknown:
            raise ConfigError(f"{self.config_path}: unknown section(s): {', '.join(sorted(unknown))}")
        unknown = set(self.section("variants")) - KNOWN_VARIANTS
        if unknown:
            raise ConfigError(f"{self.config_path}: unknown variant(s): {', '.join(sorted(unknown))} "
                              f"(supported: {', '.join(sorted(KNOWN_VARIANTS))})")
        if not self.section("podcast").get("source_feed"):
            raise ConfigError(f"{self.config_path}: [podcast] source_feed is required")

    @property
    def config_path(self) -> Path:
        return self.dir / CONFIG_NAME

    def section(self, name: str) -> Dict[str, Any]:
        """A top-level table, or {} when the file doesn't have it."""
        return self.data.get(name, {})

    def list_section(self, name: str) -> List[Dict[str, Any]]:
        """A top-level array of tables (``[[name]]``), or [] when absent."""
        return self.data.get(name, [])

    def path(self, relative: str) -> Path:
        return self.dir / relative

    # --- [podcast] ---

    @property
    def name(self) -> str:
        return self.section("podcast").get("name", self.id)

    @property
    def source_feed(self) -> str:
        return self.section("podcast")["source_feed"]

    @property
    def guid(self) -> Optional[str]:
        return self.section("podcast").get("guid")

    @property
    def timezone(self) -> str:
        return self.section("podcast").get("timezone", "UTC")

    @property
    def title_rules(self) -> TitleRules:
        """Episode title conventions from [titles]."""
        return TitleRules.from_config(self.section("titles"))

    # --- Files in the podcast directory ---

    @property
    def known_guests_path(self) -> Path:
        return self.path(self.section("guests").get("known_guests", "known_guests.json"))

    @property
    def permanent_staff_path(self) -> Path:
        return self.path(self.section("guests").get("permanent_staff", "permanent_staff.json"))

    @property
    def cache_path(self) -> Path:
        """Local copy of the source feed (``--local-cache``)."""
        return CACHE_DIR / f"{self.id}-original.xml"

    # --- Publishing ---

    @property
    def base_url(self) -> str:
        base_url = self.section("publish").get("base_url")
        if not base_url:
            raise ConfigError(f"{self.config_path}: [publish] base_url is required")
        return base_url.rstrip("/")

    @property
    def feed_file(self) -> str:
        return self.section("publish").get("feed", f"{self.id}-enriched.xml")

    @property
    def feed_url(self) -> str:
        return f"{self.base_url}/{self.feed_file}"

    @property
    def enriched_local_path(self) -> Path:
        return OUTPUT_DIR / self.feed_file

    def variant(self, name: str) -> Dict[str, Any]:
        variants = self.section("variants")
        if name not in variants:
            raise ConfigError(f"{self.config_path}: no [variants.{name}] section "
                              f"(configured: {', '.join(sorted(variants)) or 'none'})")
        return variants[name]


def _config_ids(config_name: str) -> List[str]:
    if not PODCASTS_DIR.is_dir():
        return []
    return sorted(p.parent.name for p in PODCASTS_DIR.glob(f"*/{config_name}"))


def _load_toml(config_id: Optional[str], config_name: str, option: str, env: str):
    """
    Find and parse ``podcasts/<config_id>/<config_name>``. Without an id, uses
    the ``env`` environment variable, or the only one there is.
    Returns ``(id, data, directory)``.
    """
    config_id = config_id or os.environ.get(env)
    available = _config_ids(config_name)
    if not config_id:
        if len(available) != 1:
            raise ConfigError(
                f"Velg med {option} <id>, eller sett {env}=<id> (f.eks. i .env). "
                f"Tilgjengelige: {', '.join(available) or 'ingen'}"
            )
        config_id = available[0]

    directory = PODCASTS_DIR / config_id
    config_path = directory / config_name
    if not config_path.is_file():
        raise ConfigError(f"Fant ikke {config_path}. Tilgjengelige: {', '.join(available) or 'ingen'}")
    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{config_path}: {e}") from e
    return config_id, data, directory


def load_podcast(podcast_id: Optional[str] = None) -> PodcastConfig:
    """
    Load ``podcasts/<podcast_id>/podcast.toml``.

    Without an id, uses the ``PODCAST`` environment variable, or the only
    configured podcast if there is exactly one.
    """
    return PodcastConfig(*_load_toml(podcast_id, CONFIG_NAME, "--podcast", "PODCAST"))


@dataclass
class ListConfig:
    """Parsed list.toml for a list feed (see build_list_feed.py)."""

    id: str
    data: Dict[str, Any]
    dir: Path

    @property
    def images_dir(self) -> Path:
        return self.dir / self.data.get("images_dir", "images")


def load_list(list_id: Optional[str] = None) -> ListConfig:
    """Load ``podcasts/<list_id>/list.toml`` (default: ``LIST`` env var, or the only one)."""
    return ListConfig(*_load_toml(list_id, LIST_CONFIG_NAME, "--list", "LIST"))


def add_podcast_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--podcast",
        metavar="ID",
        help="Podcast under podcasts/<ID>/ (standard: PODCAST-miljøvariabel, "
             "eller den eneste som er konfigurert)",
    )


def load_podcast_or_exit(podcast_id: Optional[str] = None) -> PodcastConfig:
    """``load_podcast`` for entry points: prints the error and exits instead of raising."""
    try:
        return load_podcast(podcast_id)
    except ConfigError as e:
        print(f"❌ {e}")
        sys.exit(1)
