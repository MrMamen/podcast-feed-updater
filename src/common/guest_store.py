"""
Higher-level operations on cdspill_known_guests.json.

All mutations of the guests/aliases structure go through here so that every
entry point (guests.py subcommands, interactive menu) behaves the same way.
The key rule: an existing guest is never overwritten, only *filled in* where
``img`` / ``href`` are missing.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote

from src.enrichment.podchaser_api import PodchaserAPI

# --- Podchaser creator helpers -------------------------------------------------


def creator_fields(creator: Dict) -> Dict[str, str]:
    """Map a Podchaser creator dict to the ``{img, href}`` fields we store."""
    fields = {}
    if creator.get("imageUrl"):
        fields["img"] = creator["imageUrl"]
    if creator.get("url"):
        fields["href"] = creator["url"]
    return fields


def best_creator_match(client: Optional[PodchaserAPI], name: str, first: int = 5) -> Optional[Dict]:
    """
    Search Podchaser for ``name`` and return the best creator match, or None.

    An exact (case-insensitive) name match wins; otherwise the first result.
    """
    if client is None:
        return None
    try:
        creators = client.search_creator(name, first=first)
    except Exception as e:  # network / API errors should not abort batch runs
        print(f"  ⚠ Feil ved søk etter {name}: {e}")
        return None
    for creator in creators:
        if creator.get("name", "").lower() == name.lower():
            return creator
    return creators[0] if creators else None


def parse_podchaser_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Return ``(creator_id, name)`` from a Podchaser creator URL such as
    ``https://www.podchaser.com/creators/aleks-gisvold-107tZxOga3``.
    """
    url = unquote(url)
    match = re.search(r"/creators/([^/]+)-([a-zA-Z0-9]+)$", url)
    if match:
        name = " ".join(word.capitalize() for word in match.group(1).split("-"))
        return match.group(2), name
    match = re.search(r"creators/([a-zA-Z0-9]+)$", url)
    if match:
        return match.group(1), None
    return None, None


def is_podchaser_url(value: str) -> bool:
    return "podchaser.com/creators/" in value


# --- Name matching --------------------------------------------------------------


def normalize_name(name: str) -> str:
    return " ".join(name.lower().split())


def find_guest_by_href(data: Dict, href: str) -> Optional[str]:
    """Return the guest key whose ``href`` equals ``href``, if any."""
    if not href:
        return None
    for guest_name, guest_data in data["guests"].items():
        if guest_data.get("href") == href:
            return guest_name
    return None


def find_guests_matching(query: str, data: Dict) -> List[str]:
    """
    Resolve a partial name ("Anette", "Hakestad") to canonical guest keys.

    Exact key/alias match wins. Otherwise every guest whose key or any alias
    contains the query (case-insensitive) is returned, sorted, deduplicated.
    """
    guests, aliases = data["guests"], data["aliases"]
    if query in guests:
        return [query]
    if query in aliases and aliases[query] in guests:
        return [aliases[query]]
    q = normalize_name(query)
    hits = {g for g in guests if q in normalize_name(g)}
    hits |= {c for a, c in aliases.items() if q in normalize_name(a) and c in guests}
    return sorted(hits)


def find_similar_guests(name: str, guests: Dict) -> List[str]:
    """Return existing guest names sharing at least one name part with ``name``."""
    parts = set(normalize_name(name).split())
    return sorted(g for g in guests if parts & set(normalize_name(g).split()))


# --- Mutations ------------------------------------------------------------------


def upsert_guest(data: Dict, name: str, creator: Optional[Dict] = None) -> List[str]:
    """
    Ensure ``name`` exists in ``data["guests"]`` and fill in any missing
    ``img``/``href`` from ``creator``. Returns a list of human-readable changes
    (empty if nothing changed).
    """
    changes = []
    guests = data["guests"]
    if name not in guests:
        guests[name] = {}
        changes.append(f"ny gjest: {name}")
    entry = guests[name]
    for key, value in creator_fields(creator or {}).items():
        if not entry.get(key):
            entry[key] = value
            changes.append(f"{key} lagt til for {name}")
    return changes


def add_alias(data: Dict, alias: str, canonical: str) -> List[str]:
    if alias == canonical or data["aliases"].get(alias) == canonical:
        return []
    data["aliases"][alias] = canonical
    return [f"alias: '{alias}' → '{canonical}'"]


def rename_guest(data: Dict, old_name: str, new_name: str) -> List[str]:
    """
    Re-key ``old_name`` to ``new_name`` (the official Podchaser name) and make
    the old name an alias, so episode titles using it still resolve.
    """
    if old_name == new_name:
        return []
    guests = data["guests"]
    guests[new_name] = guests.pop(old_name)
    changes = [f"omdøpt '{old_name}' → '{new_name}'"]
    changes += add_alias(data, old_name, new_name)
    # Repoint any aliases that targeted the old key.
    for alias, target in data["aliases"].items():
        if target == old_name and alias != old_name:
            data["aliases"][alias] = new_name
    return changes


def add_extra_episode(data: Dict, name: str, guid: str, note: str) -> bool:
    """Append an ``extra_episodes`` entry unless the GUID is already listed."""
    entry = data["guests"].setdefault(name, {})
    extra = entry.setdefault("extra_episodes", [])
    if any(ep.get("guid") == guid for ep in extra):
        return False
    extra.append({"guid": guid, "note": note})
    return True


_NOTE_EPISODE_RE = re.compile(r"\(#(\d+)\)")


def episode_number_from_note(note: str) -> Optional[int]:
    match = _NOTE_EPISODE_RE.search(note or "")
    return int(match.group(1)) if match else None


def sort_extra_episodes(data: Dict) -> None:
    """Sort every guest's ``extra_episodes`` by episode number, newest first."""
    for guest_data in data["guests"].values():
        if "extra_episodes" in guest_data:
            guest_data["extra_episodes"].sort(
                key=lambda ep: episode_number_from_note(ep.get("note", "")) or -1,
                reverse=True,
            )


# --- Queries --------------------------------------------------------------------


def guests_missing_profile(data: Dict) -> Dict[str, List[str]]:
    """Return ``{guest_name: [missing fields]}`` for guests lacking img or href."""
    missing = {}
    for name, entry in data["guests"].items():
        fields = [f for f in ("img", "href") if not entry.get(f)]
        if fields:
            missing[name] = fields
    return missing


def status_icons(entry: Dict) -> str:
    """Compact ``📷 🔗`` indicator used in menus and listings."""
    icons = ("📷" if entry.get("img") else "  ") + " " + ("🔗" if entry.get("href") else "  ")
    return icons
