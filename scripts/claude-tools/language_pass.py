#!/usr/bin/env python3
"""Helpers for the agent language pass over a transcript.

The language pass is done by subagents, one per chunk of about ten minutes,
each editing its chunk in place with the solo-track text as reference. This
tool does the mechanical parts around that:

  split    Cut a VTT into chunks at the nearest pause (>= 2 s) around every
           N-minute mark, never inside a cue. Each chunk gets a reference
           file (solo_segments from the raw cache, with slack across the
           boundary, plus the neighbouring cues as read-only context) and a
           ready prompt from language_pass_prompt.md. A copy of the chunks
           is kept in <out>/before for `measure`.
  join     Concatenate the edited chunks back into one VTT, in time order.
           Overlapping cues are clipped, delayed or combined into one
           two-speaker cue so that none ends up too short to read. Run transcribe.py --polish on
           the result afterwards.
  measure  Report what the pass changed: cues deleted, cues with changed
           text, two-speaker splits, word edit rate.
  names    List capitalised words that occur in several spellings (two
           agents choosing differently across chunks: Gunther / Gunter).
  check    For a transcript made from speaker stems (align_solo.py): list
           cues where the speaker's own track is silent, and cues whose
           words are mostly not on that track (text from a reference, or
           speech that was cut). Run it before handing the VTT over.

Usage:
    uv run python scripts/claude-tools/language_pass.py split transcripts/GK.vtt \\
        --episode-number 119 --out $SCRATCHPAD/gk --terms "Schattenjäger, Cabrit sans cor"
    # ... run one agent per $SCRATCHPAD/gk/chunkNN.prompt.md ...
    uv run python scripts/claude-tools/language_pass.py join $SCRATCHPAD/gk -o transcripts/GK.vtt
    uv run python scripts/transcribe.py -o transcripts/GK.vtt --polish
    uv run python scripts/claude-tools/language_pass.py measure $SCRATCHPAD/gk
    uv run python scripts/claude-tools/language_pass.py names transcripts/GK.vtt
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "scripts"))
from asr_common import (cue_speaker_groups, display_name, escape_text, format_ts,  # noqa: E402
                        load_corrections, parse_vtt, resolve_overlaps)

TEMPLATE = Path(__file__).with_name("language_pass_prompt.md")
TEMPLATE_STEMS = Path(__file__).with_name("language_pass_prompt_stems.md")
HOSTS = ["Sigve", "Mamen"]


# --------------------------------------------------------------------------
# split
# --------------------------------------------------------------------------
def cue_text(c: dict) -> str:
    return " ".join(c["lines"])


def render_cue(c: dict) -> str:
    lines = [escape_text(ln) for ln in c["lines"]]
    if c.get("speaker"):
        lines[0] = f"<v {c['speaker']}>{lines[0]}"
    return f"{format_ts(c['start'])} --> {format_ts(c['end'])}\n" + "\n".join(lines)


def chunk_bounds(cues: list[dict], minutes: float, min_pause: float, search: float) -> list[int]:
    """Indices where chunks start: the cue after the longest pause (>= min_pause)
    within +/- search seconds of every N-minute mark, else the mark itself."""
    starts = [0]
    mark = minutes * 60
    end = cues[-1]["start"]
    while mark < end:
        best, best_gap = None, min_pause
        for i in range(1, len(cues)):
            if abs(cues[i]["start"] - mark) > search:
                continue
            gap = cues[i]["start"] - cues[i - 1]["end"]
            if gap >= best_gap:
                best, best_gap = i, gap
        if best is None:
            best = next((i for i, c in enumerate(cues) if c["start"] >= mark), len(cues))
        if best > starts[-1]:
            starts.append(best)
        mark += minutes * 60
    return starts


def episode_meta(number: int | None) -> dict:
    if number is None:
        return {}
    try:
        from transcribe import lookup_episode
        return lookup_episode(PROJECT, number=number) or {}
    except Exception as e:  # metadata is a convenience
        print(f"(episode metadata unavailable: {e})")
        return {}


def chapter_titles(meta: dict) -> list[str]:
    url = meta.get("chapters_url")
    if not url:
        return []
    name = url.split("?")[0].split("/")[-1]
    for p in (PROJECT / "docs" / "chapters" / name, PROJECT / "chapters" / name):
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            return [c.get("title", "") for c in data.get("chapters", []) if c.get("title")]
    return []


def cmd_split(args) -> int:
    vtt = Path(args.vtt)
    cues = parse_vtt(vtt)
    raw_path = Path(args.raw) if args.raw else PROJECT / ".cache" / "raw" / (vtt.stem + ".json")
    raw = json.loads(raw_path.read_text(encoding="utf-8")) if raw_path.exists() else {}
    stems = bool(raw.get("stems"))
    solo = [] if stems else raw.get("solo_segments") or []
    reference = parse_vtt(Path(args.reference)) if args.reference else []
    if not solo and not stems:
        print(f"(no solo_segments in {raw_path}; reference files will only carry context cues)")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    corrections = load_corrections()

    meta = episode_meta(args.episode_number)
    people = meta.get("people") or []
    speakers = HOSTS + [display_name(p, corrections) for p in people]
    tagged = {c["speaker"] for c in cues if c.get("speaker")}
    clip_tags = sorted(tagged - set(speakers) - {"?"})
    terms = [t.strip() for t in (args.terms or "").split(",") if t.strip()]
    terms += [t for t in chapter_titles(meta) if not re.match(r"^(Intro|Velkommen|Neste episode|Kommentarer)", t)]
    clips = ""
    if clip_tags:
        clips = ("Game clips: cues tagged " + ", ".join(clip_tags) + " are lines from the game or "
                 "film, transcribed from the clean clip files in their own language. Keep that "
                 "language. For a cue tagged Spillklipp, replace the tag with the character's "
                 "name when the line makes it clear, otherwise leave Spillklipp.")
    template = (TEMPLATE_STEMS if stems else TEMPLATE).read_text(encoding="utf-8")

    starts = chunk_bounds(cues, args.minutes, args.min_pause, args.search)
    starts.append(len(cues))
    for n, (a, b) in enumerate(zip(starts, starts[1:]), 1):
        part = cues[a:b]
        t0, t1 = part[0]["start"], part[-1]["end"]
        (out / f"chunk{n:02d}.vtt").write_text(
            "WEBVTT\n\n" + "\n\n".join(render_cue(c) for c in part) + "\n", encoding="utf-8")
        ref = [f"# Reference for {format_ts(t0)}–{format_ts(t1)}. Read only.", ""]
        before = cues[max(0, a - args.context):a]
        after = cues[b:b + args.context]
        if before:
            ref += ["## Last cues of the previous chunk (context, already handled there)", ""]
            ref += [render_cue(c) for c in before] + [""]
        if after:
            ref += ["## First cues of the next chunk (context, handled there)", ""]
            ref += [render_cue(c) for c in after] + [""]
        if solo:
            ref += ["## Solo tracks (each speaker's own microphone, words in mix time; the speaker is certain)", ""]
            ref += [f"{format_ts(s['start'])} <v {s['speaker']}> {s['text']}"
                    for s in solo if t0 - args.slack <= s["start"] < t1 + args.slack]
        (out / f"chunk{n:02d}.ref.md").write_text("\n".join(ref) + "\n", encoding="utf-8")
        ref_line = ""
        if reference:
            # kept in a subdirectory: join only reads chunkNN.vtt in <out>
            rdir = out / "reference"
            rdir.mkdir(exist_ok=True)
            rpath = rdir / f"chunk{n:02d}.vtt"
            span = [c for c in reference if t0 - 30 <= c["start"] <= t1 + 30]
            rpath.write_text("WEBVTT\n\n" + "\n\n".join(render_cue(c) for c in span) + "\n",
                             encoding="utf-8")
            ref_line = (f"- Reference (read only): {rpath.resolve()} — an earlier transcript of the "
                        f"same time span (timestamps line up). Use it for names, terms and English "
                        f"phrases; its speaker tags may be wrong and it may contain speech that was "
                        f"cut from the episode.\n")
        prompt = template.replace("{REFERENCE}", ref_line)
        for k, v in {
            "EPISODE": meta.get("title") or vtt.stem,
            "SPEAKERS": ", ".join(speakers),
            "TAGS": ", ".join(speakers + clip_tags),
            "TERMS": ", ".join(terms) if terms else "the names in the episode title and chapters",
            "CLIPS": clips,
            "CHUNK_VTT": str((out / f"chunk{n:02d}.vtt").resolve()),
            "CHUNK_REF": str((out / f"chunk{n:02d}.ref.md").resolve()),
            "CHUNK_REPORT": str((out / f"chunk{n:02d}.report.md").resolve()),
            "GUIDELINES": str(PROJECT / "transcripts" / "TRANSCRIPT_GUIDELINES.md"),
            "CORRECTIONS": str(PROJECT / "transcripts" / "corrections.json"),
        }.items():
            prompt = prompt.replace("{" + k + "}", v)
        (out / f"chunk{n:02d}.prompt.md").write_text(prompt, encoding="utf-8")
        print(f"  chunk{n:02d}: {format_ts(t0)} - {format_ts(t1)}  {len(part)} cues")
    before_dir = out / "before"
    if before_dir.exists():
        shutil.rmtree(before_dir)
    before_dir.mkdir()
    for f in out.glob("chunk*.vtt"):
        shutil.copy(f, before_dir / f.name)
    print(f"{len(starts) - 1} chunks in {out}; one agent per chunkNN.prompt.md")
    return 0


# --------------------------------------------------------------------------
# join
# --------------------------------------------------------------------------
def cmd_join(args) -> int:
    d = Path(args.dir)
    cues: list[dict] = []
    for f in sorted(d.glob("chunk[0-9][0-9].vtt")):
        cues += parse_vtt(f)
    n = resolve_overlaps(cues)
    Path(args.output).write_text(
        "WEBVTT\n\n" + "\n\n".join(render_cue(c) for c in cues) + "\n", encoding="utf-8")
    print(f"joined {len(cues)} cues -> {args.output} (overlaps: clipped {n['clipped']}, "
          f"delayed {n['delayed']}, combined {n['combined']}); "
          f"now run: uv run python scripts/transcribe.py -o {args.output} --polish")
    return 0


# --------------------------------------------------------------------------
# measure
# --------------------------------------------------------------------------
def _plain(c: dict) -> str:
    return re.sub(r"<v [^>]+>", "", cue_text(c)).strip()


def cmd_measure(args) -> int:
    d = Path(args.dir)
    before_dir = d / "before"
    if not before_dir.exists():
        sys.stderr.write(f"No {before_dir}; `split` keeps the pre-edit copy there.\n")
        return 1
    tot = Counter()
    for fb in sorted(before_dir.glob("chunk*.vtt")):
        fa = d / fb.name
        if not fa.exists():
            continue
        b, a = parse_vtt(fb), parse_vtt(fa)
        amap = {c["ts_line"]: c for c in a}
        tot["cues_before"] += len(b)
        tot["cues_after"] += len(a)
        for c in b:
            tb = _plain(c)
            tot["words_before"] += len(tb.split())
            if c["ts_line"] not in amap:
                tot["deleted"] += 1
                continue
            ca = amap[c["ts_line"]]
            ta = _plain(ca)
            tot["words_after"] += len(ta.split())
            if any(ln.startswith("<v ") for ln in ca["lines"]):
                tot["two_speaker"] += 1
            if ca["speaker"] == "?" or "<v ?>" in "\n".join(ca["lines"]):
                tot["unsure"] += 1
            if tb == ta and c["speaker"] == ca["speaker"]:
                tot["unchanged"] += 1
            else:
                tot["changed"] += 1
                if c["speaker"] != ca["speaker"]:
                    tot["retagged"] += 1
                sm = difflib.SequenceMatcher(None, tb.split(), ta.split())
                tot["word_edits"] += sum(max(i2 - i1, j2 - j1)
                                         for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal")
    for k in ("cues_before", "cues_after", "deleted", "changed", "unchanged", "retagged",
              "two_speaker", "unsure", "words_before", "words_after", "word_edits"):
        print(f"  {k:13s} {tot[k]}")
    nb = max(1, tot["cues_before"])
    print(f"  cues touched {100 * (tot['deleted'] + tot['changed']) / nb:.1f} %, "
          f"word edit rate {100 * tot['word_edits'] / max(1, tot['words_before']):.1f} %")
    return 0


# --------------------------------------------------------------------------
# check
# --------------------------------------------------------------------------
STOP = set("ja nei og det er jo så du jeg da at i på en et som har de vi man med for men ikke "
           "der den liksom bare litt sånn".split())


def _norm(w: str) -> str:
    return re.sub(r"[^\wæøå]", "", w.lower())


def cmd_check(args) -> int:
    """Cues whose text or timing does not match the speaker's own track."""
    vtt = Path(args.vtt)
    raw_path = Path(args.raw) if args.raw else PROJECT / ".cache" / "raw" / (vtt.stem + ".json")
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    if not raw.get("stems"):
        sys.stderr.write(f"{raw_path} is not from align_solo.py's stems; nothing to check against.\n")
        return 1
    corrections = load_corrections()
    disp = {display_name(k, corrections): k for k in raw["stem_envelope"]}
    env = {disp_name: raw["stem_envelope"][full] for disp_name, full in disp.items()}
    step = raw.get("envelope_step", 0.1)
    words: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for s in raw["solo_segments"]:
        for w in s["words"]:
            words[display_name(s["speaker"], corrections)].append((w["start"], _norm(w["word"])))
    for v in words.values():
        v.sort()
    silent, foreign = [], []
    for c in parse_vtt(vtt):
        for spk, text in cue_speaker_groups(c):
            if spk not in env:
                continue
            e = env[spk][int(c["start"] / step):int(c["end"] / step) + 1]
            if max(e, default=0.0) < args.silence:
                silent.append((c, spk, text))
                continue
            toks = [t for t in (_norm(x) for x in text.split()) if len(t) >= 3 and t not in STOP]
            if len(toks) < 3:
                continue
            bag = {w for t, w in words[spk] if c["start"] - 2 <= t <= c["end"] + 2}
            hit = sum(any(t == b or (len(t) >= 4 and t[:4] == b[:4]) for b in bag) for t in toks)
            if hit / len(toks) < args.min_match:
                foreign.append((c, spk, text, hit / len(toks)))
    print(f"{len(silent)} cue(s) where the speaker's track is silent (wrong time, wrong tag, "
          f"or text that is not in the episode):")
    for c, spk, text in silent:
        print(f"  {format_ts(c['start'])} {spk:8s} {text[:80]}")
    print(f"{len(foreign)} cue(s) whose words are mostly not on the speaker's track (text taken "
          f"from a reference, or a heavy rewrite):")
    for c, spk, text, m in foreign:
        print(f"  {format_ts(c['start'])} {spk:8s} {m:.0%}  {text[:80]}")
    return 0


# --------------------------------------------------------------------------
# names
# --------------------------------------------------------------------------
def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"(.)\1+", r"\1", s)          # collapse doubled letters


def cmd_names(args) -> int:
    """Proper nouns (capitalised mid-sentence) that occur in several spellings."""
    cues = parse_vtt(Path(args.vtt))
    counts: Counter = Counter()
    for c in cues:
        text = _plain(c)
        for m in re.finditer(r"\b[A-ZÆØÅ][\wæøåÆØÅ'’-]{2,}\b", text):
            before = text[:m.start()].rstrip()
            if not before or before[-1] in ".!?…:\"«»":
                continue                      # sentence start: not evidence of a name
            counts[m.group()] += 1
    words = sorted(counts)
    groups: dict[str, set[str]] = defaultdict(set)
    for w in words:
        groups[_fold(w)].add(w)
    folded = list(groups)
    reported: set[str] = set()
    for i, k in enumerate(folded):
        close = {k}
        for j in range(i + 1, len(folded)):
            other = folded[j]
            if other[0] != k[0] or min(len(k), len(other)) < 4:
                continue
            if difflib.SequenceMatcher(None, k, other).ratio() >= args.ratio:
                close.add(other)
        spellings = set().union(*(groups[x] for x in close))
        # a plain inflection (Facebook / Facebooken, Adventure / Adventures) is not a misspelling
        base = min(spellings, key=len)
        if all(w == base or (w.startswith(base) and w[len(base):] in ("s", "e", "en", "et", "ene", "er", "a"))
               for w in spellings):
            continue
        if len(spellings) > 1 and not spellings <= reported:
            reported |= spellings
            print("  " + "  /  ".join(f"{w} ({counts[w]})"
                                      for w in sorted(spellings, key=lambda w: -counts[w])))
    if not reported:
        print("  no capitalised words with several spellings")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("split", help="cut a VTT into chunks with reference and prompt files")
    s.add_argument("vtt")
    s.add_argument("--out", required=True, help="directory for chunkNN.* files")
    s.add_argument("--raw", help="raw cache (default .cache/raw/<stem>.json)")
    s.add_argument("--episode-number", type=int, help="for title, guests and chapter terms")
    s.add_argument("--terms", help="comma-separated names/terms to spell canonically")
    s.add_argument("--minutes", type=float, default=10.0)
    s.add_argument("--min-pause", type=float, default=2.0,
                   help="shortest pause a chunk boundary may use (default 2 s)")
    s.add_argument("--search", type=float, default=60.0,
                   help="how far from the N-minute mark to look for a pause (default 60 s)")
    s.add_argument("--context", type=int, default=3, help="neighbouring cues shown as context")
    s.add_argument("--slack", type=float, default=20.0, help="solo reference overlap in seconds")
    s.add_argument("--reference", help="an earlier transcript (e.g. the published one) given to "
                                       "the agents for names, terms and English phrases")
    s.set_defaults(fn=cmd_split)
    k = sub.add_parser("check", help="cues that do not match the speaker's own track "
                                     "(raw cache from align_solo.py)")
    k.add_argument("vtt")
    k.add_argument("--raw", help="raw cache (default .cache/raw/<stem>.json)")
    k.add_argument("--silence", type=float, default=0.01,
                   help="loudest 0.1 s of the speaker's track under the cue below this = silent")
    k.add_argument("--min-match", type=float, default=0.3,
                   help="share of the cue's content words found on the speaker's track")
    k.set_defaults(fn=cmd_check)
    j = sub.add_parser("join", help="concatenate edited chunks into one VTT")
    j.add_argument("dir")
    j.add_argument("-o", "--output", required=True)
    j.set_defaults(fn=cmd_join)
    m = sub.add_parser("measure", help="what the pass changed (before/ vs edited chunks)")
    m.add_argument("dir")
    m.set_defaults(fn=cmd_measure)
    n = sub.add_parser("names", help="capitalised words spelled several ways")
    n.add_argument("vtt")
    n.add_argument("--ratio", type=float, default=0.85)
    n.set_defaults(fn=cmd_names)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
