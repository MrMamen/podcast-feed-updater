#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Normalize a YouTube/ASR VTT file into a clean, sentence-based VTT.

Pipeline:
  1. Apply ASR error corrections (error_fixes, word_fixes, regex_fixes, phrase_fixes).
  2. Parse the karaoke/rollup VTT into (timestamp, token) pairs.
  3. Group tokens into sentences (respecting abbreviations).
  4. Split long cues at natural break-points (commas, conjunctions).
  5. Remove filler words ("eh", "ehm", "uhm", "øh") unless --keep-fillers.
  6. Apply <v Speaker> tags based on configured start/end phrases.
  7. Wrap text at --line-width and emit a clean WebVTT file.

Configuration
-------------
Corrections are loaded from JSON. By default the script looks for
  transcripts/corrections.json (permanent, all episodes).

A per-episode config can be passed with --config. It may set
"extends": "path/to/base.json" (relative to the config file) to inherit
rules from a parent config. List fields (word_fixes, phrase_fixes, ...)
are concatenated; scalar fields (default_speaker, line_width, ...) are
overridden.

Usage
-----
    scripts/normalize_transcript.py input.vtt \
        --config transcripts/my-episode.config.json \
        -o output.vtt

See transcripts/corrections.json for the shared schema and
transcripts/paskelabyrint-2026.solo.config.json for a full example.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# ----------------------------------------------------------------------
# VTT parsing
# ----------------------------------------------------------------------

TS_INNER = r"\d\d:\d\d:\d\d\.\d{3}"
TS_PATTERN = rf"<{TS_INNER}>"
CUE_RE = re.compile(
    rf"^({TS_INNER})\s*-->\s*({TS_INNER})[^\n]*\n(.*?)"
    rf"(?=^{TS_INNER}\s*-->|\Z)",
    re.MULTILINE | re.DOTALL,
)


def time_to_seconds(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def seconds_to_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


# ----------------------------------------------------------------------
# Correction passes
# ----------------------------------------------------------------------

def _tag_seq(words: list[str], bare_first: bool) -> str:
    """Regex matching a sequence of <c>word</c> tokens joined by timestamps.

    bare_first=True  -> FIRSTWORD<ts><c> rest</c>...  (cue-start form)
    bare_first=False -> <c> FIRSTWORD</c><ts><c> rest</c>...  (mid-cue form)
    """
    parts = []
    for i, w in enumerate(words):
        esc = re.escape(w)
        if i == 0:
            parts.append(esc if bare_first else rf"<c>\s*{esc}</c>")
        else:
            parts.append(rf"{TS_PATTERN}<c>\s*{esc}</c>")
    return "".join(parts)


def _apply_phrase_fix(content: str, src: list[str], dst: str) -> str:
    """Replace a phrase in clean text AND in both tagged cue forms.

    Per-word timing within the phrase is collapsed into one <c> block,
    but cue-level timing is preserved.
    """
    content = content.replace(" ".join(src), dst)

    # Bare-first tagged form (start of cue)
    pat_bare = _tag_seq(src, bare_first=True)
    dst_words = dst.split()
    if len(dst_words) > 1:
        repl_bare = f'{dst_words[0]}<c> {" ".join(dst_words[1:])}</c>'
    else:
        repl_bare = dst
    content = re.sub(pat_bare, repl_bare, content)

    # All-in-<c> form (mid-cue)
    content = re.sub(_tag_seq(src, bare_first=False), f"<c> {dst}</c>", content)
    return content


def apply_corrections(content: str, config: dict[str, Any]) -> str:
    # 1. Cross-line raw string fixes (e.g. "need for\nSpeeda?")
    for fix in config.get("error_fixes", []):
        content = content.replace(fix["from"], fix["to"])

    # 2. Single-token substring replacements
    for old, new in config.get("word_fixes", []):
        if old and old != new:
            content = content.replace(old, new)

    # 3. Word-boundary / arbitrary regex fixes
    for fix in config.get("regex_fixes", []):
        content = re.sub(fix["pattern"], fix["replacement"], content)

    # 4. Multi-word phrase fixes (handles tag-spanning)
    for fix in config.get("phrase_fixes", []):
        content = _apply_phrase_fix(content, fix["from"], fix["to"])

    # 5. Cleanup of chain-replacement artifacts
    for fix in config.get("cleanup_fixes", []):
        content = content.replace(fix["from"], fix["to"])

    return content


# ----------------------------------------------------------------------
# Token extraction
# ----------------------------------------------------------------------

def parse_tokens(content: str) -> list[tuple[str, str]]:
    """Return a chronologically sorted list of (start_time, text) tokens.

    Processes only lines with <c> tags (the per-word timing lines).
    Falls back to bare content lines when a cue has no <c> markup
    (YouTube sometimes drops a word on its own line).
    """
    tokens: list[tuple[str, str]] = []
    running = ""

    for m in CUE_RE.finditer(content):
        cue_start = m.group(1)
        body = m.group(3)
        lines = body.split("\n")
        tagged = [l for l in lines if "<c>" in l]
        bare = [l for l in lines if l.strip() and "<c>" not in l and "<" not in l]

        for line in tagged:
            clean = re.sub(r"</?c[^>]*>", "", line)
            parts = re.split(rf"<({TS_INNER})>", clean)
            current = cue_start
            for i, part in enumerate(parts):
                if i % 2 == 0:
                    text = part.strip()
                    if text:
                        tokens.append((current, text))
                        running += " " + text
                else:
                    current = part

        if not tagged and bare:
            last = re.sub(r"\s+", " ", bare[-1]).strip()
            if last and last not in running:
                tokens.append((cue_start, last))
                running += " " + last

    # Dedupe by (time, text)
    seen, uniq = set(), []
    for t, text in tokens:
        k = (t, text)
        if k not in seen:
            seen.add(k)
            uniq.append((t, text))
    return sorted(uniq, key=lambda x: time_to_seconds(x[0]))


# ----------------------------------------------------------------------
# Sentence grouping + cue splitting
# ----------------------------------------------------------------------

_INITIAL_RE = re.compile(r"^[A-ZÆØÅ]\.$")


def group_sentences(tokens: list[tuple[str, str]],
                    abbreviations: list[str]) -> list[tuple[str, str]]:
    abbrev = set(abbreviations)

    def is_end(text: str) -> bool:
        s = text.rstrip()
        if not s or s[-1] not in ".?!":
            return False
        last = s.split()[-1] if s.split() else s
        if last in abbrev:
            return False
        if _INITIAL_RE.match(last):
            return False
        return True

    sentences: list[tuple[str, str]] = []
    cur: list[tuple[str, str]] = []
    for t, text in tokens:
        cur.append((t, text))
        if is_end(text):
            sentences.append((cur[0][0], " ".join(x[1] for x in cur)))
            cur = []
    if cur:
        sentences.append((cur[0][0], " ".join(x[1] for x in cur)))

    # Collapse adjacent duplicate words (common after cross-cue phrase fixes)
    return [(t, re.sub(r"\b(\w+)\s+\1\b", r"\1", text, flags=re.IGNORECASE))
            for t, text in sentences]


def compute_cues(sentences: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
    cues = []
    for i, (start, text) in enumerate(sentences):
        if i + 1 < len(sentences):
            end = sentences[i + 1][0]
        else:
            end = seconds_to_time(time_to_seconds(start) + 3.0)
        cues.append((start, end, text))
    return cues


def apply_post_fixes(sentences: list[tuple[str, str]],
                     post_fixes: list[dict[str, str]]) -> list[tuple[str, str]]:
    """Run substring replacements on joined sentence text.

    Useful for errors that span VTT cue boundaries (e.g. "need for Speeda"
    where "need for" and "Speeda?" are in different cues before normalization).
    """
    out = []
    for start, text in sentences:
        for fix in post_fixes:
            text = text.replace(fix["from"], fix["to"])
        out.append((start, text))
    return out


def split_long_cue(start: str, end: str, text: str,
                   max_seconds: float) -> list[tuple[str, str, str]]:
    dur = time_to_seconds(end) - time_to_seconds(start)
    if dur <= max_seconds:
        return [(start, end, text)]

    bps = [i for i, c in enumerate(text) if c == ","]
    if not bps:
        for conj in (" og ", " men ", " som ", " fordi ", " så ", " hvor "):
            bps.extend(m.start() for m in re.finditer(re.escape(conj), text))
    if not bps:
        bps = [i for i, c in enumerate(text) if c == " "]
        if not bps:
            return [(start, end, text)]

    mid = len(text) // 2
    split_pos = min(bps, key=lambda p: abs(p - mid))
    first = text[:split_pos + 1].strip().rstrip(",").rstrip()
    second = text[split_pos + 1:].strip()
    if not (first and second):
        return [(start, end, text)]

    split_time = time_to_seconds(start) + dur * (split_pos + 1) / len(text)
    mid_ts = seconds_to_time(split_time)
    return (split_long_cue(start, mid_ts, first, max_seconds)
            + split_long_cue(mid_ts, end, second, max_seconds))


# ----------------------------------------------------------------------
# Filler removal, speaker tags, rendering
# ----------------------------------------------------------------------

def remove_fillers(cues: list[tuple[str, str, str | None, str]],
                   fillers: list[str]) -> list[tuple[str, str, str | None, str]]:
    def clean(text: str) -> str:
        for f in fillers:
            esc = re.escape(f)
            text = re.sub(rf"\s+\b{esc}\b(?![.,?!])", "", text)
            text = re.sub(rf"\s+\b{esc},", ",", text)
            text = re.sub(rf"\s+\b{esc}\.", ".", text)
        text = re.sub(r"  +", " ", text)
        text = re.sub(r" ,", ",", text).replace(" .", ".")
        return text.strip()

    return [(s, e, spk, clean(t)) for s, e, spk, t in cues]


def apply_speakers(cues: list[tuple[str, str, str]],
                   speakers: list[dict[str, str]],
                   default: str | None) -> list[tuple[str, str, str | None, str]]:
    current = default
    out = []
    for start, end, text in cues:
        for spk in speakers:
            if spk.get("start_phrase") and spk["start_phrase"] in text:
                current = spk["name"]
                break
        out.append((start, end, current, text))
        for spk in speakers:
            if current == spk.get("name") and spk.get("end_phrase") and spk["end_phrase"] in text:
                current = default
                break
    return out


def wrap_text(text: str, width: int) -> str:
    words = text.split()
    lines, cur, cur_len = [], [], 0
    for w in words:
        extra = 1 if cur else 0
        if cur_len + len(w) + extra > width and cur:
            lines.append(" ".join(cur))
            cur, cur_len = [w], len(w)
        else:
            cur.append(w)
            cur_len += len(w) + extra
    if cur:
        lines.append(" ".join(cur))
    return "\n".join(lines)


def render_vtt(cues: list[tuple[str, str, str | None, str]],
               line_width: int, language: str) -> str:
    out = ["WEBVTT", "Kind: captions", f"Language: {language}", ""]
    for start, end, spk, text in cues:
        out.append(f"{start} --> {end}")
        body = wrap_text(text, line_width)
        out.append(f"<v {spk}>{body}" if spk else body)
        out.append("")
    return "\n".join(out)


# ----------------------------------------------------------------------
# Config loading
# ----------------------------------------------------------------------

_LIST_KEYS = {"word_fixes", "regex_fixes", "phrase_fixes",
              "cleanup_fixes", "error_fixes", "post_fixes",
              "filler_words", "abbreviations", "speakers"}


def _merge_config(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    """Merge child into parent.

    - List keys are appended (parent items first) UNLESS the child explicitly
      sets the key to an empty list, which means "override to empty".
    - Scalar keys are overridden by the child.
    """
    merged: dict[str, Any] = {
        k: list(v) if isinstance(v, list) else v for k, v in parent.items()
    }
    for k, v in child.items():
        if k in _LIST_KEYS and k in merged and isinstance(merged[k], list):
            # empty list in child = explicit override to empty
            merged[k] = list(v) if v == [] else merged[k] + v
        else:
            merged[k] = v
    return merged


def load_config(path: Path, _seen: set[Path] | None = None) -> dict[str, Any]:
    """Load JSON config with 'extends' inheritance (relative paths)."""
    path = path.resolve()
    _seen = _seen or set()
    if path in _seen:
        raise ValueError(f"Cyclic extends: {path}")
    _seen.add(path)

    data = json.loads(path.read_text(encoding="utf-8"))
    extends = data.pop("extends", None)
    if not extends:
        return data

    parent_path = (path.parent / extends).resolve()
    parent = load_config(parent_path, _seen)
    return _merge_config(parent, data)


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", type=Path, help="Input VTT (YouTube/ASR karaoke format)")
    parser.add_argument("-o", "--output", type=Path,
                        help="Output VTT (default: overwrite input)")
    parser.add_argument("--config", type=Path,
                        help="Per-episode config JSON")
    parser.add_argument("--corrections", type=Path,
                        help="Permanent corrections JSON "
                             "(default: <project>/transcripts/corrections.json)")
    parser.add_argument("--line-width", type=int,
                        help="Max chars per line (default: config value or 42)")
    parser.add_argument("--max-cue-seconds", type=float,
                        help="Split cues longer than this (default: config or 8)")
    parser.add_argument("--backup", action="store_true",
                        help="Save <input>.bak before overwriting")
    parser.add_argument("--keep-fillers", action="store_true",
                        help="Do not remove eh/ehm/uhm/øh")
    args = parser.parse_args()

    if not args.input.exists():
        sys.stderr.write(f"Error: {args.input} does not exist\n")
        return 1

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent

    # Build effective config: permanent corrections, then optional per-episode
    corrections_path = args.corrections or (project_root / "transcripts" / "corrections.json")
    config: dict[str, Any] = {}
    if corrections_path.exists():
        config = load_config(corrections_path)
    if args.config:
        episode = load_config(args.config)
        config = _merge_config(config, episode)

    line_width   = args.line_width   or config.get("line_width", 42)
    max_cue_sec  = args.max_cue_seconds or config.get("max_cue_seconds", 8.0)
    language     = config.get("language", "no")
    abbreviations= config.get("abbreviations", ["Mr.", "Dr."])
    fillers      = [] if args.keep_fillers else config.get("filler_words", ["eh", "ehm", "uhm", "øh"])
    speakers     = config.get("speakers", []) or []
    default_spk  = config.get("default_speaker")

    content = args.input.read_text(encoding="utf-8")
    output_path = args.output or args.input

    if args.backup and output_path == args.input:
        bak = args.input.with_suffix(args.input.suffix + ".bak")
        bak.write_text(content, encoding="utf-8")
        print(f"Backup: {bak}")

    content = apply_corrections(content, config)

    tokens = parse_tokens(content)
    if not tokens:
        sys.stderr.write("Error: no tokens parsed. Is this a YouTube karaoke VTT?\n")
        return 1

    sentences = group_sentences(tokens, abbreviations)
    sentences = apply_post_fixes(sentences, config.get("post_fixes", []))
    cues = compute_cues(sentences)

    expanded = []
    for s, e, t in cues:
        expanded.extend(split_long_cue(s, e, t, max_cue_sec))
    cues = expanded

    tagged = apply_speakers(cues, speakers, default_spk)
    if fillers:
        tagged = remove_fillers(tagged, fillers)

    output = render_vtt(tagged, line_width, language)
    output_path.write_text(output, encoding="utf-8")

    print(f"Wrote {output_path}: {len(tagged)} cues, {len(output):,} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
