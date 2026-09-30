#!/usr/bin/env python3
"""Use the Reaper project and the solo tracks as speaker ground truth.

Every self-edited episode folder has the Reaper project (`.rpp`) and one
recording per microphone. The project lists every item on every track with
its position in the mix, its length and its offset into the source file, so
it is an exact map of who is audible when, and of which seconds of each
solo track survived the edit. This script reads that map and rewrites the
raw cache from `transcribe.py` so that

  * speaker tags come from the solo tracks: each solo recording is
    transcribed on its own (transcribe.py --no-diarization, run here when
    the cache is missing), its words are moved into mix time through the
    items, and those words become the diarization. Where no solo word
    exists the Reaper item itself is the fallback. pyannote is not used.
  * speech the mix transcript skipped is filled from the solo words
    (stretches of >= 2.5 s with 4+ words, the same rule as the built-in
    gap fill),
  * items on other tracks given with --item (a game intro, a film clip)
    are transcribed from the clean file, in their own language, and
    replace the mix text inside their span with the given tag,
  * spans covered only by non-speaker tracks (music, effects, game audio)
    are listed so hallucinated cues there can be checked,
  * the mapped solo text is kept in the cache under "solo_segments" as
    reference material for the language pass.

Then re-render with `transcribe.py -o <vtt> --render-only`. Runs from the
`.orig.json` copy of the cache, so it can be repeated with a better mapping.

Usage:
    uv run python scripts/transcribe.py -o transcripts/TA.vtt --episode-number 120 \\
        --no-diarization
    uv run python scripts/align_solo.py -o transcripts/TA.vtt --episode-number 120 \\
        --item "Total Annihilation - Intro Cinematic.wav=Forteller|en"
    uv run python scripts/transcribe.py -o transcripts/TA.vtt --render-only

Speaker tracks are recognised by name: the hosts' tracks ("Mamen", "Sigve"),
a track named like a person in the episode's <podcast:person> list or in the
speaker profiles (first name is enough), or an explicit --track "Roar=Roar
Granevang". Tracks that map to nobody are treated as non-speech. `--list`
prints the tracks and files and stops.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

from asr_common import DEFAULT_AUDIO_LIBRARY, find_episode_audio, format_ts

HOST_TRACKS = {"mamen": "Mr. Mamen", "mr. mamen": "Mr. Mamen", "mr mamen": "Mr. Mamen",
               "sigve": "Sigve"}
NON_SPEECH_HINTS = ("musikk", "music", "intro", "outro", "sfx", "effekt", "lyd", "jingle",
                    "spill", "game", "klipp", "clip", "voices", "master")
DEFAULT_ITEM_MODEL = "Systran/faster-whisper-large-v3"   # multilingual, for --item clips
MIN_GAP = 2.5        # seconds of mix silence before solo words are inserted
MIN_GAP_WORDS = 4
WORD_PAD = 1.0       # items only count as fallback this far from any solo word


# --------------------------------------------------------------------------
# Reaper project
# --------------------------------------------------------------------------
def parse_rpp(path: Path) -> list[dict]:
    """Tracks as {"name", "mute", "items": [{pos, len, soffs, rate, mute, file}]}."""
    tracks: list[dict] = []
    cur = item = None
    stack: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("<"):
            tag = s.split()[0]
            stack.append(tag)
            if tag == "<TRACK":
                cur = {"name": "", "mute": 0, "items": []}
                tracks.append(cur)
            elif tag == "<ITEM" and cur is not None:
                item = {"pos": 0.0, "len": 0.0, "soffs": 0.0, "rate": 1.0, "mute": 0,
                        "file": None}
                cur["items"].append(item)
            continue
        if s == ">":
            stack.pop()
            if stack and stack[-1] == "<TRACK":
                item = None
            continue
        top = stack[-1] if stack else ""
        parts = s.split()
        if not parts:
            continue
        if top == "<TRACK" and cur is not None and item is None:
            if parts[0] == "NAME":
                cur["name"] = s[5:].strip().strip('"')
            elif parts[0] == "MUTESOLO":
                cur["mute"] = int(parts[1])
        elif item is not None and top == "<ITEM":
            if parts[0] == "POSITION":
                item["pos"] = float(parts[1])
            elif parts[0] == "LENGTH":
                item["len"] = float(parts[1])
            elif parts[0] == "SOFFS":
                item["soffs"] = float(parts[1])
            elif parts[0] == "PLAYRATE":
                item["rate"] = float(parts[1])
            elif parts[0] == "MUTE":
                item["mute"] = int(parts[1])
        elif item is not None and top == "<SOURCE" and parts[0] == "FILE":
            m = re.match(r'FILE\s+"([^"]*)"', s)      # FILE "name.mp3" 1  (trailing flags)
            item["file"] = m.group(1) if m else s[5:].strip()
    for t in tracks:
        t["items"] = [i for i in t["items"] if not i["mute"] and i["file"] and i["len"] > 0]
    return [t for t in tracks if not t["mute"]]


def find_rpp(folder: Path) -> Path | None:
    cands = [p for p in folder.iterdir()
             if p.suffix.lower() == ".rpp" and "newtemp" not in p.name.lower()]
    if not cands:
        return None
    return max(cands, key=lambda p: p.stat().st_mtime)


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def basename(win_path: str) -> str:
    return win_path.replace("\\", "/").rsplit("/", 1)[-1]


def resolve(folder: Path, fname: str) -> Path | None:
    name = _nfc(basename(fname)).lower()
    for cand in folder.iterdir():
        if _nfc(cand.name).lower() == name:
            return cand
    return None


# --------------------------------------------------------------------------
# Speaker mapping
# --------------------------------------------------------------------------
def known_people(project: Path, episode: int | None) -> list[str]:
    names: list[str] = []
    prof = project / "transcripts" / "speaker_profiles.npy"
    if prof.exists():
        try:
            import numpy as np
            names += list(np.load(prof, allow_pickle=True).item().keys())
        except Exception:
            pass
    if episode is not None:
        try:
            sys.path.insert(0, str(project / "scripts"))
            from transcribe import lookup_episode
            meta = lookup_episode(project, number=episode)
            names += list((meta or {}).get("people") or [])
        except Exception as e:  # metadata is a convenience only
            print(f"  (episode metadata unavailable: {e})")
    seen: dict[str, None] = {}
    for n in names:
        seen.setdefault(n, None)
    return list(seen)


def map_tracks(tracks: list[dict], people: list[str], overrides: dict[str, str]) -> dict[str, str]:
    """Track name -> full speaker name for the tracks that are a person."""
    out: dict[str, str] = {}
    for t in tracks:
        if not t["items"]:
            continue
        name = t["name"]
        low = name.lower().strip()
        if name in overrides:
            out[name] = overrides[name]
        elif low in HOST_TRACKS:
            out[name] = HOST_TRACKS[low]
        else:
            hits = [p for p in people
                    if low == p.lower() or low == p.split()[0].lower()
                    or low in p.lower()]
            if len(hits) == 1 and not any(h in low for h in NON_SPEECH_HINTS):
                out[name] = hits[0]
    return out


# --------------------------------------------------------------------------
# Transcription of clean files
# --------------------------------------------------------------------------
def ensure_cache(project: Path, audio: Path, tag: str, lang: str, episode: int | None,
                 no_transcribe: bool, model: str | None = None) -> dict:
    raw_dir = project / ".cache" / "raw"
    cache = raw_dir / f"{audio.stem}.{tag}.json"
    if not cache.exists():
        if no_transcribe:
            raise SystemExit(f"Missing {cache}; run transcribe.py --no-diarization on {audio}.")
        print(f"  Transcribing {audio.name} ({lang})...")
        cmd = [sys.executable, str(project / "scripts" / "transcribe.py"), str(audio),
               "-o", str(raw_dir / f"{audio.stem}.{tag}.vtt"), "--no-diarization",
               "--language", lang]
        if episode is not None:
            cmd += ["--episode-number", str(episode)]
        if model:
            cmd += ["--model", model]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            sys.stderr.write(r.stderr[-2000:])
            raise SystemExit(f"transcribe.py failed on {audio.name}")
    return json.loads(cache.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Mapping solo words into the mix
# --------------------------------------------------------------------------
def map_words(raw: dict, items: list[dict], speaker: str) -> tuple[list[dict], int]:
    """Solo words -> mix time through the items of their file. Returns (words, dropped)."""
    items = sorted(items, key=lambda i: i["soffs"])
    out, dropped = [], 0
    for seg in raw["segments"]:
        for w in seg["words"]:
            mid = (w["start"] + w["end"]) / 2
            it = next((i for i in items if i["soffs"] <= mid < i["soffs"] + i["len"] * i["rate"]),
                      None)
            if it is None:
                dropped += 1
                continue
            f = lambda t, it=it: it["pos"] + (t - it["soffs"]) / it["rate"]
            out.append({"start": f(w["start"]), "end": f(w["end"]), "word": w["word"],
                        "speaker": speaker, "_item": id(it)})
    return out, dropped


def words_to_segments(words: list[dict], max_words: int = 40, max_pause: float = 1.0) -> list[dict]:
    segs: list[dict] = []
    for w in sorted(words, key=lambda w: w["start"]):
        cur = segs[-1] if segs else None
        if (cur and cur["speaker"] == w["speaker"] and cur["_item"] == w["_item"]
                and w["start"] - cur["end"] < max_pause and len(cur["words"]) < max_words):
            cur["words"].append(w)
            cur["end"] = w["end"]
        else:
            segs.append({"start": w["start"], "end": w["end"], "speaker": w["speaker"],
                         "_item": w["_item"], "words": [w]})
    for s in segs:
        s["text"] = "".join(w["word"] for w in s["words"]).strip()
        s["words"] = [{"start": w["start"], "end": w["end"], "word": w["word"]} for w in s["words"]]
        del s["_item"]
    return segs


def split_segment_at(segs: list[dict], lo: float, hi: float) -> list[dict]:
    """Split any segment spanning [lo, hi] so its cues render in time order."""
    out = []
    for s in segs:
        if s["start"] < lo and s["end"] > hi and s.get("words"):
            before = [w for w in s["words"] if w["end"] <= lo]
            after = [w for w in s["words"] if w["start"] >= hi]
            if before and after and len(before) + len(after) == len(s["words"]):
                for part in (before, after):
                    out.append({**s, "start": part[0]["start"], "end": part[-1]["end"],
                                "text": "".join(w["word"] for w in part).strip(), "words": part})
                continue
        out.append(s)
    return out


def subtract(span: tuple[float, float], covered: list[tuple[float, float]]) -> list[tuple[float, float]]:
    a, b = span
    out = []
    cur = a
    for x, y in covered:
        if y <= cur:
            continue
        if x >= b:
            break
        if x > cur:
            out.append((cur, x))
        cur = max(cur, y)
    if cur < b:
        out.append((cur, b))
    return out


def merge_spans(spans: list[tuple[float, float]], gap: float = 0.5) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(spans):
        if out and a - out[-1][1] < gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------
def build(raw: dict, speaker_words: list[dict], speaker_items: list[dict],
          inserts: list[dict], non_speech: list[tuple[float, float]]) -> dict:
    segs = [dict(s) for s in raw["segments"]]
    diar: list[dict] = []

    # 1) clean non-speaker items (game intro etc.) replace the mix text in their span
    for ins in inserts:
        lo, hi = ins["start"] - 0.5, ins["end"] + 0.5
        n0 = len(segs)
        segs = [s for s in segs if s["end"] <= lo or s["start"] >= hi]
        segs = split_segment_at(segs, lo, hi)
        segs += ins["segments"]
        diar.append({"start": lo, "end": hi, "speaker": ins["speaker"]})
        print(f"  {ins['speaker']:22s} {format_ts(ins['start'])} - {format_ts(ins['end'])}: "
              f"replaced {n0 - len(segs) + len(ins['segments'])} mix segment(s) "
              f"with {len(ins['segments'])} from the clean file")

    # 2) solo words as diarization
    sw = sorted(speaker_words, key=lambda w: w["start"])
    diar += [{"start": w["start"], "end": w["end"], "speaker": w["speaker"]} for w in sw]

    # 3) Reaper items as fallback where no solo word is near
    covered = merge_spans([(w["start"] - WORD_PAD, w["end"] + WORD_PAD) for w in sw], gap=0)
    covered += [(i["start"] - 0.5, i["end"] + 0.5) for i in inserts]
    covered = merge_spans(covered, gap=0)
    n_fb = 0
    for it in speaker_items:
        for a, b in subtract((it["start"], it["end"]), covered):
            if b - a > 0.3:
                diar.append({"start": a, "end": b, "speaker": it["speaker"]})
                n_fb += 1
    diar.sort(key=lambda d: d["start"])

    # 4) gaps in the mix text filled from solo words
    mw = sorted((w for s in segs for w in s.get("words", [])), key=lambda w: w["start"])
    bounds = [(0.0, mw[0]["start"])] + [(a["end"], b["start"]) for a, b in zip(mw, mw[1:])]
    bounds.append((mw[-1]["end"], raw.get("duration", mw[-1]["end"] + 1)))
    fills: list[list[dict]] = []
    for a, b in bounds:
        if b - a < MIN_GAP:
            continue
        inside = [w for w in sw if a + 0.3 <= w["start"] and w["end"] <= b - 0.3]
        run: list[dict] = []
        for w in inside:
            if run and (w["speaker"] != run[-1]["speaker"] or w["start"] - run[-1]["end"] > 2.0):
                if len(run) >= MIN_GAP_WORDS:
                    fills.append(run)
                run = []
            run.append(w)
        if len(run) >= MIN_GAP_WORDS:
            fills.append(run)
    fills.sort(key=lambda r: r[0]["start"])
    for prev, nxt in zip(fills, fills[1:]):      # overlapping voices: clip the earlier one
        if prev[-1]["end"] > nxt[0]["start"]:
            prev[-1] = {**prev[-1], "end": nxt[0]["start"]}
    for run in fills:
        lo, hi = run[0]["start"], run[-1]["end"]
        segs = split_segment_at(segs, lo, hi)
        segs.append({"start": lo, "end": hi,
                     "text": "".join(w["word"] for w in run).strip(),
                     "words": [{"start": w["start"], "end": w["end"], "word": w["word"]} for w in run],
                     "solo_fill": True})
    segs.sort(key=lambda s: s["start"])
    fill_s = sum(r[-1]["end"] - r[0]["start"] for r in fills)
    print(f"  solo words as turns: {len(sw)}, item fallback spans: {n_fb}, "
          f"gaps filled from solo: {len(fills)} ({fill_s:.0f} s, "
          f"{sum(len(r) for r in fills)} words)")
    for r in fills:
        print(f"    {format_ts(r[0]['start'])} {r[0]['speaker'][:12]:12s} "
              f"{''.join(w['word'] for w in r).strip()[:80]}")

    # 5) cues that no speaker supports: likely game audio / hallucination
    speaker_cover = merge_spans([(w["start"], w["end"]) for w in sw]
                                + [(i["start"], i["end"]) for i in speaker_items]
                                + [(i["start"], i["end"]) for i in inserts])
    orphans = []
    for s in segs:
        if s.get("solo_fill"):
            continue
        if not any(min(s["end"], b) - max(s["start"], a) > 0.2 for a, b in speaker_cover):
            in_ns = any(min(s["end"], b) - max(s["start"], a) > 0 for a, b in non_speech)
            orphans.append((s, in_ns))
    if orphans:
        print(f"  {len(orphans)} segment(s) outside every speaker item "
              f"(M = inside a music/effects item; check for game audio or hallucination):")
        for s, in_ns in orphans:
            print(f"    {format_ts(s['start'])} {'M' if in_ns else ' '} {s['text'][:80]}")

    smap = {w["speaker"]: w["speaker"] for w in sw}
    smap.update({i["speaker"]: i["speaker"] for i in speaker_items})
    smap.update({i["speaker"]: i["speaker"] for i in inserts})
    solo_segments = words_to_segments(
        [{**w, "_item": w.get("_item", 0)} for w in sw])
    return {**raw, "segments": segs, "diarization": diar, "speaker_map": smap,
            "solo_segments": solo_segments,
            "non_speech_spans": [[a, b] for a, b in non_speech],
            "diarization_pyannote": raw.get("diarization"),
            "speaker_map_pyannote": raw.get("speaker_map")}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", type=Path, required=True,
                    help="VTT path given to transcribe.py (selects .cache/raw/<stem>.json)")
    ap.add_argument("--episode-number", type=int, required=True)
    ap.add_argument("--library", type=Path, default=DEFAULT_AUDIO_LIBRARY)
    ap.add_argument("--rpp", type=Path, help="Reaper project (default: newest .rpp in the folder)")
    ap.add_argument("--track", action="append", default=[],
                    help='"<track name>=<Full speaker name>" (repeatable)')
    ap.add_argument("--item", action="append", default=[],
                    help='"<file on a non-speaker track>=<Tag>[|lang]": transcribe the clean '
                         'file and put its text in the mix with that tag (repeatable)')
    ap.add_argument("--item-model", default=DEFAULT_ITEM_MODEL,
                    help="Whisper model for --item files in another language than Norwegian "
                         f"(default: {DEFAULT_ITEM_MODEL}). NB-Whisper translates English "
                         "clips into Norwegian even with --language en.")
    ap.add_argument("--list", action="store_true", help="Print tracks, items and files; stop")
    ap.add_argument("--no-transcribe", action="store_true",
                    help="Fail instead of transcribing solo files whose cache is missing")
    args = ap.parse_args()

    project = Path(__file__).resolve().parent.parent
    mix_path = find_episode_audio(args.episode_number, args.library)
    folder = mix_path.parent
    rpp = args.rpp or find_rpp(folder)
    if rpp is None:
        sys.stderr.write(f"No .rpp in {folder}\n")
        return 1
    print(f"Reaper project: {rpp.name}")
    tracks = parse_rpp(rpp)

    overrides = dict(p.partition("=")[::2] for p in args.track)
    overrides = {k.strip(): v.strip() for k, v in overrides.items()}
    people = known_people(project, args.episode_number)
    who = map_tracks(tracks, people, overrides)

    speaker_items: list[dict] = []
    non_speech: list[tuple[float, float]] = []
    files_by_speaker: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in tracks:
        if not t["items"]:
            continue
        total = sum(i["len"] for i in t["items"])
        files = sorted({basename(i["file"]) for i in t["items"]})
        role = who.get(t["name"])
        print(f"  track {t['name']!r:24s} {len(t['items']):4d} items {total / 60:6.1f} min  "
              f"-> {role or 'non-speech'}   files: {', '.join(files)[:90]}")
        for i in t["items"]:
            span = {"start": i["pos"], "end": i["pos"] + i["len"]}
            if role:
                speaker_items.append({**span, "speaker": role})
                files_by_speaker[(role, basename(i["file"]))].append(i)
            else:
                non_speech.append((span["start"], span["end"]))
    non_speech = merge_spans(non_speech)
    # A recording belongs to one microphone. When a file also appears on another
    # speaker's track (an item dragged onto the wrong track), tag those items with
    # the owner, i.e. the speaker whose track uses the file most.
    use: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for (role, fname), items in files_by_speaker.items():
        use[fname][role] += sum(i["len"] for i in items)
    for fname, by_role in use.items():
        if len(by_role) < 2:
            continue
        owner = max(by_role, key=by_role.get)
        for role in [r for r in by_role if r != owner]:
            moved = files_by_speaker.pop((role, fname))
            files_by_speaker[(owner, fname)] += moved
            for i in moved:
                for si in speaker_items:
                    if si["speaker"] == role and si["start"] == i["pos"]:
                        si["speaker"] = owner
            print(f"  ⚠ {fname}: {len(moved)} item(s) ({sum(i['len'] for i in moved):.0f} s) on the "
                  f"{role!r} track belong to {owner}'s microphone; tagged {owner}")
    if args.list:
        return 0
    if not who:
        sys.stderr.write("No speaker tracks recognised; give --track NAME=Full Name.\n")
        return 1

    # solo tracks
    speaker_words: list[dict] = []
    for (role, fname), items in sorted(files_by_speaker.items()):
        path = resolve(folder, fname)
        if path is None:
            print(f"  ⚠ {role}: {fname} not in {folder}; using Reaper items only for it")
            continue
        raw = ensure_cache(project, path, "solo", "no", args.episode_number, args.no_transcribe)
        words, dropped = map_words(raw, items, role)
        speaker_words += words
        print(f"  {role:22s} {path.name}: {len(words)} words in the mix, {dropped} cut out")

    # clean non-speaker items
    inserts: list[dict] = []
    for spec in args.item:
        fname, _, tag = spec.partition("=")
        tag, _, lang = tag.partition("|")
        fname, tag, lang = fname.strip(), tag.strip(), (lang.strip() or "no")
        path = resolve(folder, fname)
        if path is None:
            print(f"  ⚠ --item {fname}: not in {folder}")
            continue
        occurrences = [i for t in tracks if not who.get(t["name"]) for i in t["items"]
                       if _nfc(basename(i["file"])).lower() == _nfc(fname).lower()]
        if not occurrences:
            print(f"  ⚠ --item {fname}: no item with that file on a non-speaker track")
            continue
        raw = ensure_cache(project, path, "item", lang, args.episode_number, args.no_transcribe,
                           model=None if lang == "no" else args.item_model)
        for it in occurrences:
            words, _ = map_words(raw, [it], tag)
            if not words:
                continue
            segs = words_to_segments([{**w, "_item": 0} for w in words])
            for s in segs:
                del s["speaker"]
            inserts.append({"start": words[0]["start"], "end": words[-1]["end"],
                            "speaker": tag, "segments": segs})

    raw_dir = project / ".cache" / "raw"
    raw_path = raw_dir / (args.output.stem + ".json")
    if not raw_path.exists():
        sys.stderr.write(f"No raw cache {raw_path}; run transcribe.py -o {args.output} first.\n")
        return 1
    orig = raw_path.with_suffix(".orig.json")
    if not orig.exists():
        shutil.copy(raw_path, orig)
    print(f"Merging into {raw_path.relative_to(project)} (from {orig.name})...")
    out = build(json.loads(orig.read_text(encoding="utf-8")), speaker_words, speaker_items,
                inserts, non_speech)
    raw_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"Done. Re-render with:\n  uv run python scripts/transcribe.py -o {args.output} --render-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
