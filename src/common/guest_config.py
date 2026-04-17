"""Shared helpers for reading and writing cdspill_known_guests.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple

KNOWN_GUESTS_PATH = Path("config/cdspill_known_guests.json")

_DEFAULT_COMMENT = (
    "Known guests with Podchaser profile data and name aliases. "
    "Add new guests using: uv run python3 scripts/guests/lookup_guest.py 'Guest Name'"
)


def load_known_guests_data(path: Path = KNOWN_GUESTS_PATH) -> Dict:
    """
    Return the full known_guests JSON structure (with `guests` and `aliases`).

    If the file does not exist, returns a fresh skeleton. Callers that need
    to know whether the file existed should check ``path.exists()`` first.
    """
    if not path.exists():
        return {"_comment": _DEFAULT_COMMENT, "guests": {}, "aliases": {}}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("guests", {})
    data.setdefault("aliases", {})
    return data


def load_known_guests(path: Path = KNOWN_GUESTS_PATH) -> Tuple[Dict, Dict]:
    """Return ``(guests, aliases)`` from known_guests.json."""
    data = load_known_guests_data(path)
    return data.get("guests", {}), data.get("aliases", {})


def save_known_guests(data: Dict, path: Path = KNOWN_GUESTS_PATH) -> None:
    """
    Write known_guests data back to disk, sorting guests and aliases
    alphabetically and adding a trailing newline.
    """
    data["guests"] = dict(sorted(data.get("guests", {}).items()))
    data["aliases"] = dict(sorted(data.get("aliases", {}).items()))

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def resolve_alias(name: str, aliases: Dict[str, str]) -> str:
    """Return the canonical name for ``name``, following aliases if present."""
    return aliases.get(name, name)
