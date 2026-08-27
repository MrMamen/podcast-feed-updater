#!/usr/bin/env python3
"""
Rapporter og statistikk over cd SPILL-feeden.

    uv run analyze.py                     # interaktiv meny
    uv run analyze.py rank                # gjester rangert etter antall opptredener
    uv run analyze.py guest "Navn"        # alle episoder en gjest har vært med i (delvis navn ok)
    uv run analyze.py length [--asc|--no-sort] [--no-bonus]   # episoder etter varighet
    uv run analyze.py cache               # last ned / oppdater lokal kopi av feeden

Rapportene leser fra den lokale cachen (.cache/cdspill-original.xml) og laster
den ned automatisk hvis den mangler. Bonusepisoder ekskluderes fra gjestetall.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from itertools import groupby
from typing import Dict, List, Optional, Tuple

import inquirer

from src.common.episodes import Episode, iter_episodes, parse_duration
from src.common.feed_loader import download_cache, load_feed
from src.common.guest_config import load_known_guests, load_known_guests_data, resolve_alias
from src.common.guest_store import episode_number_from_note, find_guests_matching
from src.common.podcast_utils import extract_guests_from_title, is_bonus_episode

CANCEL = "❌ Avbryt"


def feed() -> List[Episode]:
    return list(iter_episodes(load_feed(use_cache=True, auto_download=True, quiet=True)))


# --- rank -----------------------------------------------------------------------


def count_title_appearances(episodes: List[Episode], aliases: Dict) -> Dict[str, int]:
    counter: Dict[str, int] = defaultdict(int)
    for ep in episodes:
        if is_bonus_episode(ep.title):
            continue
        for guest in extract_guests_from_title(ep.title):
            counter[resolve_alias(guest, aliases)] += 1
    return dict(counter)


def count_contributions(known_guests: Dict, aliases: Dict) -> Dict[str, int]:
    counter: Dict[str, int] = defaultdict(int)
    for name, data in known_guests.items():
        canonical = resolve_alias(name, aliases)
        counter[canonical] += sum(
            1 for ep in data.get("extra_episodes", []) if not is_bonus_episode(ep.get("note", ""))
        )
    return {k: v for k, v in counter.items() if v}


def cmd_rank(args) -> None:
    known_guests, aliases = load_known_guests()
    episodes = feed()
    full = count_title_appearances(episodes, aliases)
    contrib = count_contributions(known_guests, aliases)
    names = set(full) | set(contrib)
    if not names:
        print("Ingen gjester funnet!")
        return

    rows = sorted(
        ((n, full.get(n, 0), contrib.get(n, 0)) for n in names),
        key=lambda r: (-r[1], -r[2], r[0]),
    )
    print("\n" + "=" * 85)
    print("GJESTESTATISTIKK ETTER ANTALL FULLSTENDIGE OPPTREDENER (bonusepisoder ekskludert)")
    print("=" * 85)
    rank = 1
    for full_count, group in groupby(rows, key=lambda r: r[1]):
        print(f"\n{full_count} FULLSTENDIGE OPPTREDENER:" if full_count else "\nKUN BIDRAG:")
        print("-" * 85)
        print(f"{'#':<6} {'Full':<6} {'Bidrag':<8} {'Totalt':<7} Gjest")
        print("-" * 85)
        for name, f, c in group:
            print(f"{rank:<6} {f:<6} {c:<8} {f + c:<7} {name}")
            rank += 1
    print("\n" + "=" * 85)
    print(f"Totalt: {len(names)} unike gjester")
    print(f"  • {sum(full.values())} fullstendige opptredener")
    print(f"  • {sum(contrib.values())} bidrag")
    print()


# --- guest ----------------------------------------------------------------------


def cmd_guest(args) -> None:
    data = load_known_guests_data()
    known_guests, aliases = data["guests"], data["aliases"]
    name = args.name
    hits = find_guests_matching(name, data)
    if not hits:
        print(f"❌ Ingen gjest matcher '{name}'")
        sys.exit(1)
    canonical = hits[0] if len(hits) == 1 else pick(f"Flere treff på '{name}' – hvem?", [*hits, CANCEL])
    if canonical is None:
        return
    if canonical != name:
        print(f"ℹ️  Tolker '{name}' som: {canonical}")

    episodes = feed()
    full: List[Tuple[str, str]] = []  # (episode_num, title)
    seen = set()
    for ep in episodes:
        if is_bonus_episode(ep.title):
            continue
        guests = {resolve_alias(g, aliases) for g in extract_guests_from_title(ep.title)}
        if canonical in guests:
            full.append((ep.episode_num, ep.title))
            seen.add(ep.guid)

    contrib: List[Tuple[str, str]] = []
    for key in {canonical, *(a for a, c in aliases.items() if c == canonical)}:
        for ep in known_guests.get(key, {}).get("extra_episodes", []):
            note = ep.get("note", "")
            if is_bonus_episode(note) or ep.get("guid") in seen:
                continue
            seen.add(ep.get("guid"))
            num = episode_number_from_note(note)
            contrib.append((str(num) if num else "", note))

    def show(heading: str, rows: List[Tuple[str, str]]) -> None:
        if not rows:
            return
        rows.sort(key=lambda r: int(r[0]) if r[0] else 0, reverse=True)
        print(f"\n{heading}")
        print("-" * 80)
        for num, title in rows:
            label = f"#{num}" if num else "N/A"
            print(f"{label:<6} {title[:69] + '...' if len(title) > 72 else title}")

    print("\n" + "=" * 80)
    print(f"EPISODER MED {canonical.upper()}")
    print("=" * 80)
    if not full and not contrib:
        print(f"\n❌ Ingen episoder funnet for {canonical}")
        return
    show("FULLSTENDIGE OPPTREDENER (nevnt i episodetittel):", full)
    show("BIDRAG (manuelt lagt til, ikke hele episoden):", contrib)
    print("\n" + "-" * 80)
    print(f"Totalt: {len(full) + len(contrib)} opptredener ({len(full)} fullstendige, {len(contrib)} bidrag)\n")


# --- length ---------------------------------------------------------------------


def _colors() -> Dict[str, str]:
    on = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    codes = {"reset": "\033[0m", "bold": "\033[1m", "yellow": "\033[33m", "green": "\033[32m", "red": "\033[31m"}
    return codes if on else {k: "" for k in codes}


def format_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def cmd_length(args) -> None:
    c = _colors()
    rows: List[Tuple[str, int, str]] = []
    for ep in feed():
        seconds = parse_duration(ep.duration)
        if seconds is None:
            print(f"⚠ Mangler/ugyldig varighet: {ep.title}")
            continue
        rows.append((ep.title or "(uten tittel)", seconds, ep.episode_type))

    if args.no_bonus:
        before = len(rows)
        rows = [r for r in rows if r[2] != "bonus"]
        print(f"✓ Ekskluderte {before - len(rows)} bonusepisoder")
    if args.asc:
        rows.sort(key=lambda r: r[1])
        heading = "SORTERT ETTER LENGDE (KORTEST TIL LENGST)"
    elif args.no_sort:
        heading = "I FEED-REKKEFØLGE (NYESTE FØRST)"
    else:
        rows.sort(key=lambda r: r[1], reverse=True)
        heading = "SORTERT ETTER LENGDE (LENGST TIL KORTEST)"
    if not rows:
        print("Ingen episoder.")
        return

    longest, shortest = max(rows, key=lambda r: r[1]), min(rows, key=lambda r: r[1])
    print("\n" + "=" * 95)
    print(f"CD SPILL EPISODER {heading}")
    print("=" * 95)
    print(f"{'#':<5} {'Varighet':<10} {'Type':<7} Tittel")
    print("-" * 95)
    for i, row in enumerate(rows, 1):
        title, seconds, ep_type = row
        shown_type = "normal" if ep_type == "full" else ep_type
        prefix = (
            c["bold"] + c["green"] if row is longest
            else c["bold"] + c["red"] if row is shortest
            else c["yellow"] if ep_type == "bonus"
            else ""
        )
        print(f"{prefix}{i:<5} {format_duration(seconds):<10} {shown_type:<7} {title}{c['reset'] if prefix else ''}")

    total = sum(r[1] for r in rows)
    print("\n" + "=" * 95)
    print(f"{'Antall episoder:':<20}{len(rows)}")
    print(f"{'Total spilletid:':<20}{format_duration(total)}")
    print(f"{'Gjennomsnitt:':<20}{format_duration(total // len(rows))}")
    print(f"{'Lengste:':<20}{format_duration(longest[1])} — {longest[0]}")
    print(f"{'Korteste:':<20}{format_duration(shortest[1])} — {shortest[0]}")
    print()


def cmd_cache(args) -> None:
    download_cache()


# --- menu / CLI -----------------------------------------------------------------


def pick(message: str, choices: List[str]) -> Optional[str]:
    answers = inquirer.prompt([inquirer.List("x", message=message, choices=choices, carousel=True)])
    if not answers or answers["x"] == CANCEL:
        return None
    return answers["x"]


def menu(parser: argparse.ArgumentParser) -> None:
    options = {
        "🏆 Gjester rangert etter antall opptredener": ["rank"],
        "🎙  Episoder for én gjest": ["guest"],
        "⏱  Episoder etter varighet (lengst først)": ["length"],
        "⏱  Episoder etter varighet (kortest først)": ["length", "--asc"],
        "⏱  Episoder i feed-rekkefølge": ["length", "--no-sort"],
        "⬇️  Oppdater lokal kopi av feeden": ["cache"],
    }
    choice = pick("Hva vil du se?", [*options, CANCEL])
    if choice is None:
        return
    argv = list(options[choice])
    if argv[0] == "guest":
        answers = inquirer.prompt([inquirer.Text("x", message="Gjestenavn")])
        name = (answers or {}).get("x", "").strip()
        if not name:
            return
        argv.append(name)
    elif argv[0] == "length":
        answers = inquirer.prompt([inquirer.Confirm("x", message="Ekskluder bonusepisoder?", default=False)])
        if answers and answers["x"]:
            argv.append("--no-bonus")
    args = parser.parse_args(argv)
    args.func(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rapporter over cd SPILL-feeden")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("rank", help="Gjester rangert etter opptredener").set_defaults(func=cmd_rank)

    p = sub.add_parser("guest", help="Alle episoder for én gjest")
    p.add_argument("name")
    p.set_defaults(func=cmd_guest)

    p = sub.add_parser("length", help="Episoder etter varighet")
    order = p.add_mutually_exclusive_group()
    order.add_argument("--asc", action="store_true", help="Kortest først")
    order.add_argument("--no-sort", action="store_true", help="Feed-rekkefølge")
    p.add_argument("--no-bonus", action="store_true", help="Ekskluder bonusepisoder")
    p.set_defaults(func=cmd_length)

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
