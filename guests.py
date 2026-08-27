#!/usr/bin/env python3
"""
Vedlikehold av gjester i config/cdspill_known_guests.json.

Én inngangsport for alt som har med gjester å gjøre. Uten argumenter får du en
interaktiv meny; med underkommando kan det scriptes:

    uv run guests.py                          # interaktiv meny
    uv run guests.py add "Gjestenavn"         # søk Podchaser, legg til / fyll inn
    uv run guests.py add https://www.podchaser.com/creators/navn-id
    uv run guests.py add "Fullt Navn" --alias "Kort Navn"
    uv run guests.py refresh [Navn]           # fyll inn manglende bilde/URL, oppdater endrede bilder
                                              # (Navn kan være delvis: "Anette", "Hakestad")
    uv run guests.py sync                     # legg til nye gjester funnet i episodetitler
    uv run guests.py episode "#106"           # hent gjester for en episode fra Podchaser
    uv run guests.py list                     # vis alle gjester med status
    uv run guests.py cache                    # last ned lokal kopi av feeden

Felles regel: en eksisterende gjest overskrives aldri – bare manglende
``img``/``href`` fylles inn. Offisielt Podchaser-navn brukes som nøkkel,
navnevarianter fra episodetitler legges som alias.
"""

from __future__ import annotations

import argparse
import sys
from typing import Dict, List, Optional

import inquirer
from dotenv import load_dotenv

from src.common.episodes import find_episode, iter_episodes
from src.common.feed_loader import download_cache, load_feed
from src.common.guest_config import (
    KNOWN_GUESTS_PATH,
    load_known_guests_data,
    resolve_alias,
    save_known_guests,
)
from src.common.guest_store import (
    add_alias,
    add_extra_episode,
    best_creator_match,
    creator_fields,
    find_guest_by_href,
    find_guests_matching,
    find_similar_guests,
    guests_missing_profile,
    is_podchaser_url,
    normalize_name,
    parse_podchaser_url,
    rename_guest,
    sort_extra_episodes,
    status_icons,
    upsert_guest,
)
from src.common.podcast_utils import extract_guests_from_title, strip_episode_suffix
from src.enrichment.podchaser_api import PodchaserAPI, from_env

load_dotenv()

CDSPILL_PODCAST_ID = "1540724"
CANCEL = "❌ Avbryt"


# --- Small interactive helpers -------------------------------------------------


def pick(message: str, choices: List[str], default: Optional[str] = None) -> Optional[str]:
    """Arrow-key selection. Returns None if cancelled (Ctrl-C or CANCEL)."""
    answers = inquirer.prompt(
        [inquirer.List("x", message=message, choices=choices, default=default, carousel=True)]
    )
    if not answers or answers["x"] == CANCEL:
        return None
    return answers["x"]


def confirm(message: str, default: bool = True) -> bool:
    answers = inquirer.prompt([inquirer.Confirm("x", message=message, default=default)])
    return bool(answers and answers["x"])


def ask_text(message: str) -> Optional[str]:
    answers = inquirer.prompt([inquirer.Text("x", message=message)])
    value = (answers or {}).get("x", "").strip()
    return value or None


def report(changes: List[str]) -> None:
    for change in changes:
        print(f"  ✓ {change}")


def save(data: Dict, changes: List[str]) -> None:
    if changes:
        save_known_guests(data)
        print(f"\n💾 Lagret {len(changes)} endring(er) til {KNOWN_GUESTS_PATH}")
        print("💡 Kjør 'uv run enrich_cdspill.py' for å bruke oppdaterte data")
    else:
        print("\n(ingen endringer)")


def describe_creator(creator: Dict) -> str:
    img = "📷" if creator.get("imageUrl") else "  "
    return f"{img} {creator['name']}  ({creator.get('url', 'ingen URL')})"


def resolve_guest(data: Dict, query: str) -> Optional[str]:
    """Turn a full/partial name or alias into one guest key, asking if ambiguous."""
    hits = find_guests_matching(query, data)
    if not hits:
        print(f"❌ Ingen gjest matcher '{query}'")
        return None
    if len(hits) == 1:
        if hits[0] != query:
            print(f"ℹ️  Tolker '{query}' som: {hits[0]}")
        return hits[0]
    return pick(f"Flere treff på '{query}' – hvem?", [*hits, CANCEL])


# --- Core: add / match one guest -----------------------------------------------


def choose_creator(client: PodchaserAPI, query: str) -> Optional[Dict]:
    """Search Podchaser for ``query`` (name or URL) and let the user pick."""
    if is_podchaser_url(query):
        creator_id, name = parse_podchaser_url(query)
        if not name:
            print(f"❌ Klarte ikke tolke URL: {query}")
            return None
        print(f"🔍 Søker etter '{name}' (fra URL, id {creator_id})...")
        creators = client.search_creator(name, first=5)
        # Prefer the result whose URL actually ends with the id from the URL.
        for creator in creators:
            if creator.get("url", "").endswith(creator_id):
                return creator
    else:
        print(f"🔍 Søker Podchaser etter '{query}'...")
        creators = client.search_creator(query, first=5)

    if not creators:
        print(f"❌ Ingen treff for '{query}'")
        return None
    if len(creators) == 1:
        print(f"✓ Ett treff: {describe_creator(creators[0])}")
        return creators[0]

    by_label = {describe_creator(c): c for c in creators}
    choice = pick("Hvilken person?", list(by_label) + [CANCEL])
    return by_label.get(choice) if choice else None


def resolve_existing_key(data: Dict, creator: Dict, searched_name: Optional[str]) -> Optional[str]:
    """Find the key an existing entry for this creator lives under, if any."""
    guests, aliases = data["guests"], data["aliases"]
    podchaser_name = creator["name"]

    for candidate in (
        find_guest_by_href(data, creator.get("url", "")),
        podchaser_name if podchaser_name in guests else None,
        aliases.get(podchaser_name),
        searched_name if searched_name in guests else None,
        aliases.get(searched_name) if searched_name else None,
    ):
        if candidate and candidate in guests:
            return candidate

    for name in guests:
        if normalize_name(name) == normalize_name(podchaser_name):
            return name
    return None


def add_guest(
    data: Dict,
    client: Optional[PodchaserAPI],
    query: str,
    *,
    alias: Optional[str] = None,
    creator: Optional[Dict] = None,
    interactive: bool = True,
) -> List[str]:
    """
    Add or complete one guest. ``query`` is a name (as written in an episode
    title) or a Podchaser URL. ``creator`` may be pre-fetched (e.g. from
    episode credits) to skip the search. Returns list of changes made.
    """
    searched_name = None if is_podchaser_url(query) else query

    if creator is None:
        if client is None:
            # Offline: at least make sure the name exists.
            return upsert_guest(data, searched_name) if searched_name else []
        creator = choose_creator(client, query)
        if creator is None:
            return []

    podchaser_name = creator["name"]
    key = resolve_existing_key(data, creator, searched_name)

    if key is None and interactive:
        # Unknown person: could still be an existing guest under another spelling.
        similar = find_similar_guests(podchaser_name, data["guests"])
        if searched_name:
            similar = sorted(set(similar) | set(find_similar_guests(searched_name, data["guests"])))
        new_label = f"➕ Legg til som ny gjest: {podchaser_name}"
        all_label = "🔎 Velg blant alle gjester"
        labels = {f"= {status_icons(data['guests'][g])} {g}": g for g in similar}
        choice = pick(
            f"Er '{podchaser_name}' en eksisterende gjest?",
            [new_label, *labels, all_label, CANCEL],
        )
        if choice is None:
            return []
        if choice == all_label:
            labels = {f"= {status_icons(data['guests'][g])} {g}": g for g in sorted(data["guests"])}
            choice = pick("Velg gjest", [*labels, CANCEL])
            if choice is None:
                return []
        key = labels.get(choice)  # None when "new guest" was chosen

    changes: List[str] = []
    if key is None:
        key = podchaser_name
    elif key != podchaser_name:
        # Existing entry under a non-official name → rename, keep old as alias.
        do_rename = True
        if interactive:
            do_rename = confirm(
                f"Podchaser-navn '{podchaser_name}' ≠ '{key}'. Bruk Podchaser-navnet som hovednavn?"
            )
        if do_rename:
            changes += rename_guest(data, key, podchaser_name)
            key = podchaser_name

    changes += upsert_guest(data, key, creator)

    if searched_name and searched_name != key and searched_name not in data["aliases"]:
        wanted = True
        if interactive and searched_name != podchaser_name:
            wanted = confirm(f"Legg til alias '{searched_name}' → '{key}'?")
        if wanted:
            changes += add_alias(data, searched_name, key)
    if alias:
        changes += add_alias(data, alias, key)

    if not changes:
        print(f"✓ '{key}' er allerede komplett – ingen endringer nødvendig")
    report(changes)
    return changes


# --- Subcommands ----------------------------------------------------------------


def cmd_add(args) -> None:
    data = load_known_guests_data()
    client = from_env(required=True)
    changes = add_guest(data, client, args.query, alias=args.alias)
    save(data, changes)


def cmd_refresh(args) -> None:
    """
    Walk through guests and (a) fill in missing img/href, (b) detect that the
    Podchaser image has changed and offer to update it.
    """
    data = load_known_guests_data()
    guests = data["guests"]
    if args.name:
        key = resolve_guest(data, args.name)
        if key is None:
            sys.exit(1)
        targets = [key]
    else:
        targets = sorted(guests)

    missing = guests_missing_profile(data)
    print(f"🔎 Sjekker {len(targets)} gjest(er) mot Podchaser "
          f"({sum(1 for t in targets if t in missing)} mangler bilde/URL)")

    client = from_env(required=True)
    changes: List[str] = []
    for name in targets:
        entry = guests[name]
        creator = best_creator_match(client, name)
        if creator is None:
            print(f"— {name}: ⚠ ikke funnet på Podchaser")
            continue
        exact = normalize_name(creator["name"]) == normalize_name(name)
        same_href = bool(creator.get("url")) and creator["url"] == entry.get("href")
        if not (exact or same_href):
            if args.yes or not confirm(
                f"— {name}: beste treff er '{creator['name']}' ({creator.get('url')}). Godta?",
                default=False,
            ):
                print(f"— {name}: ⏭ hoppet over")
                continue

        made = upsert_guest(data, name, creator)  # fills only missing fields

        new_img = creator.get("imageUrl")
        old_img = entry.get("img")
        if new_img and old_img and new_img != old_img:
            print(f"— {name}: 🖼 bildet på Podchaser er endret")
            print(f"    nå:      {old_img}")
            print(f"    Podchaser: {new_img}")
            if args.yes or confirm("    Oppdater til nytt bilde?", default=True):
                entry["img"] = new_img
                made.append(f"img oppdatert for {name}")
            else:
                print("    beholder eksisterende")

        if made:
            report(made)
            changes += made
        else:
            print(f"— {name}: ✓ uendret")
    save(data, changes)


def cmd_sync(args) -> None:
    data = load_known_guests_data()
    known = set(data["guests"]) | set(data["aliases"])
    feed_xml = load_feed(use_cache=False)

    in_titles = sorted({g for ep in iter_episodes(feed_xml) for g in extract_guests_from_title(ep.title)})
    new = [g for g in in_titles if g not in known]
    print(f"\n📦 {len(data['guests'])} gjester, {len(data['aliases'])} alias i fila")
    print(f"🔍 {len(in_titles)} unike gjester i episodetitler, {len(new)} nye")
    if not new:
        return
    for g in new:
        print(f"  • {g}")

    client = from_env(required=False)
    if client is None:
        print("⚠ Ingen Podchaser-tilgang – legger til uten profildata")

    changes: List[str] = []
    for name in new:
        print(f"\n— {name}")
        creator = best_creator_match(client, name)
        if creator and normalize_name(creator["name"]) != normalize_name(name):
            # Non-exact match: ask (or skip profile data with --yes to stay safe).
            if args.yes or not confirm(
                f"  Beste treff er '{creator['name']}' ({creator.get('url')}). Godta?", default=False
            ):
                creator = None
        if creator:
            changes += add_guest(data, client, name, creator=creator, interactive=not args.yes)
        else:
            print("  ⚠ Ikke funnet – legger til uten profildata")
            changes += upsert_guest(data, name)
    save(data, changes)


def cmd_episode(args) -> None:
    data = load_known_guests_data()
    feed_xml = load_feed(use_cache=False)
    episode = find_episode(feed_xml, args.query)
    if episode is None:
        print(f"❌ Fant ikke episode: {args.query}")
        sys.exit(1)
    label = f"#{episode.episode_num} " if episode.episode_num else ""
    print(f"✓ {label}{episode.title}\n  {episode.guid}")

    client = from_env(required=True)
    clean_title = strip_episode_suffix(episode.title)
    pc_episode = client.search_episode(CDSPILL_PODCAST_ID, clean_title, first=5)
    if not pc_episode:
        print("❌ Fant ikke episoden på Podchaser")
        sys.exit(1)
    print(f"✓ Podchaser: {pc_episode['title']} ({pc_episode.get('url', '')})")

    credits = client.fetch_episode_credits(pc_episode["id"])
    guests, ambiguous = [], []
    print("\n📋 Credits:")
    for credit in credits:
        creator = credit.get("creator", {})
        role = credit.get("role", {}).get("title", "")
        print(f"  • {creator.get('name', '?')}: {role}")
        if "guest" in role.lower():
            guests.append(creator)
        elif role.lower() in ("consultant", "contributor", "participant"):
            ambiguous.append(creator)
    if ambiguous:
        print(f"\n⚠ {len(ambiguous)} person(er) med uklar rolle ble ikke tatt med automatisk.")
    if not guests:
        print("\n⚠ Ingen gjester registrert for episoden på Podchaser")
        return

    changes: List[str] = []
    title_guests = {resolve_alias(g, data["aliases"]) for g in extract_guests_from_title(episode.title)}
    for creator in guests:
        name = creator["name"]
        print(f"\n— {name}")
        key = resolve_existing_key(data, creator, name)
        if key is None:
            changes += add_guest(data, client, name, creator=creator)
            key = resolve_existing_key(data, creator, name)
            if key is None:
                print("  ⏭ Hoppet over")
                continue
        else:
            changes += upsert_guest(data, key, creator)
        if key in title_guests:
            print("  ℹ Står i episodetittelen – auto-detekteres, trenger ikke extra_episodes")
            continue
        note = episode.title
        if episode.episode_num and f"(#{episode.episode_num})" not in note:
            note = f"{note} (#{episode.episode_num})"
        if add_extra_episode(data, key, episode.guid, note):
            changes.append(f"extra_episodes: {key} ← {note}")
            print(f"  ✓ Lagt til i extra_episodes")
        else:
            print("  ✓ Har allerede episoden i extra_episodes")
    sort_extra_episodes(data)
    save(data, changes)


def cmd_list(args) -> None:
    data = load_known_guests_data()
    print(f"\n{'📷 🔗':<6} Navn")
    print("-" * 60)
    for name in sorted(data["guests"]):
        entry = data["guests"][name]
        extras = f"  (+{len(entry['extra_episodes'])} extra)" if entry.get("extra_episodes") else ""
        aliases = [a for a, t in data["aliases"].items() if t == name]
        alias_str = f"  alias: {', '.join(aliases)}" if aliases else ""
        print(f"{status_icons(entry):<6} {name}{extras}{alias_str}")
    missing = guests_missing_profile(data)
    print("-" * 60)
    print(f"{len(data['guests'])} gjester, {len(data['aliases'])} alias, {len(missing)} mangler bilde/URL")


def cmd_cache(args) -> None:
    download_cache()


# --- Interactive menu -----------------------------------------------------------


MENU = [
    ("➕ Legg til ny gjest (navn eller Podchaser-URL)", "add"),
    ("🖼  Oppdater bilde/URL fra Podchaser (alle, eller én gjest)", "refresh"),
    ("🔄 Finn nye gjester i episodetitler", "sync"),
    ("🎙  Hent gjester for en episode fra Podchaser", "episode"),
    ("📋 Vis alle gjester", "list"),
    ("⬇️  Last ned lokal kopi av feeden", "cache"),
]


def menu(parser: argparse.ArgumentParser) -> None:
    labels = {label: cmd for label, cmd in MENU}
    choice = pick("Hva vil du gjøre?", list(labels) + [CANCEL])
    if choice is None:
        return
    cmd = labels[choice]
    argv = [cmd]
    if cmd == "add":
        query = ask_text("Navn eller Podchaser-URL")
        if not query:
            return
        argv.append(query)
    elif cmd == "episode":
        query = ask_text("Episode (#nummer, tittel eller GUID)")
        if not query:
            return
        argv.append(query)
    elif cmd == "refresh":
        name = ask_text("Gjestenavn (tom = alle)")
        if name:
            argv.append(name)
    args = parser.parse_args(argv)
    args.func(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Vedlikehold gjester i cdspill_known_guests.json")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("add", help="Legg til / fyll inn én gjest fra navn eller Podchaser-URL")
    p.add_argument("query", help="Gjestenavn (som i episodetittel) eller Podchaser-URL")
    p.add_argument("--alias", help="Legg også til denne navnevarianten som alias")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("refresh", help="Fyll inn manglende img/href og oppdater endrede bilder fra Podchaser")
    p.add_argument("name", nargs="?", help="Begrens til én gjest")
    p.add_argument("-y", "--yes", action="store_true", help="Ikke spør; hopp over usikre treff, godta nye bilder")
    p.set_defaults(func=cmd_refresh)

    p = sub.add_parser("sync", help="Legg til nye gjester funnet i episodetitler")
    p.add_argument("-y", "--yes", action="store_true", help="Ikke spør; usikre treff legges til uten data")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("episode", help="Hent gjester for én episode fra Podchaser-credits")
    p.add_argument("query", help="#nummer, tittel eller GUID")
    p.set_defaults(func=cmd_episode)

    sub.add_parser("list", help="Vis alle gjester med status").set_defaults(func=cmd_list)
    sub.add_parser("cache", help="Last ned lokal kopi av feeden").set_defaults(func=cmd_cache)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command is None:
        menu(parser)
    else:
        args.func(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAvbrutt")
        sys.exit(1)
