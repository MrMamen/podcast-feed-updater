#!/usr/bin/env python3
"""Chapter-guided diarization relabeler.

Strategy:
  1. Load chapter JSON and categorize each chapter window:
     - 'overvakerne'  : title contains 'fra Overvåkerne'
     - 'caller'       : title matches a known guest name (from cdspill_known_guests.json)
                        or passes a conservative name heuristic
     - 'mamen_anchor' : title contains 'Mamen' (e.g. 'MrMamen kårer...')
     - 'sigve_anchor' : title starts with 'Sigve kårer' / 'Sigve ' + verb
     - 'regular'      : everything else (game discussions, intros, outros)

  2. Run pyannote diarization with --speakers hint (default 2).

  3. From anchor windows determine which SPEAKER_XX = Mr. Mamen / Sigve.

  4. Relabel the VTT:
     - caller window      → caller name (or 'Innringer')
     - overvakerne window → 'Overvåkerne'
     - anchor/regular     → diarization result mapped to host names

Usage:
    uv run python scripts/diarize_chapters.py <audio> \\
        --chapters chapters/Episode_chapters.json \\
        --apply-to-vtt transcripts/Episode.vtt [--hosts-only] [--profiles ...]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

from asr_common import (
    DEFAULT_DIARIZATION_MODEL,
    PROFILE_THRESHOLD,
    display_name,
    format_ts,
    load_corrections,
    load_audio,
    load_diarization_pipeline,
    load_hf_token,
    match_profiles,
    project_root,
    run_diarization,
    setup_cuda_paths,
    speaker_for_range,
    t2s,
)

setup_cuda_paths()


# --------------------------------------------------------------------------
# Chapter categorization
# --------------------------------------------------------------------------
def load_known_names(root: Path) -> set[str]:
    """Load all guest names + aliases from cdspill_known_guests.json."""
    path = root / "config" / "cdspill_known_guests.json"
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    names: set[str] = set(data.get("guests", {}).keys())
    for alias in data.get("aliases", {}).keys():
        names.add(alias)
    return names


def categorize_chapters(chapters: list[dict], known_names: set[str]) -> list[dict]:
    """
    Returns list of windows with keys:
      start, end, title, category, label
    category: 'regular' | 'caller' | 'overvakerne' | 'mamen_anchor' | 'sigve_anchor'
    label: what to use in <v ...> tag (None for regular — diarization decides)
    """
    result = []
    for i, ch in enumerate(chapters):
        start = ch["startTime"]
        end = chapters[i + 1]["startTime"] if i + 1 < len(chapters) else float("inf")
        title = ch["title"]

        if "fra Overvåkerne" in title or title == "Overvåkerne":
            cat, label = "overvakerne", "Overvåkerne"
        elif re.search(r"\bMamen\b|\bMrMamen\b", title, re.IGNORECASE):
            cat, label = "mamen_anchor", "Mr. Mamen"
        elif re.match(r"^Sigve\s+(kårer|velger|presenterer)", title, re.IGNORECASE):
            cat, label = "sigve_anchor", "Sigve"
        elif title in known_names:
            cat, label = "caller", title  # use real name
        else:
            cat, label = "regular", None

        result.append({"start": start, "end": end, "title": title,
                        "category": cat, "label": label})
    return result


def category_for_time(windows: list[dict], t: float) -> dict | None:
    """Find the chapter window containing time t."""
    for w in windows:
        if w["start"] <= t < w["end"]:
            return w
    return None


# --------------------------------------------------------------------------
# Host-only audio extraction
# --------------------------------------------------------------------------
def extract_host_audio(audio_wav, windows: list[dict], sample_rate: int = 16000):
    """
    Concatenate only 'regular', 'mamen_anchor', 'sigve_anchor' windows.
    Returns (hosts_wav, segment_map) where segment_map is a list of
    (hosts_start_sec, hosts_end_sec, orig_start_sec, orig_end_sec).
    """
    import numpy as np
    host_cats = {"regular", "mamen_anchor", "sigve_anchor"}
    chunks, segment_map = [], []
    cursor = 0.0
    audio_dur = len(audio_wav) / sample_rate

    for w in windows:
        if w["category"] not in host_cats:
            continue
        o_start = w["start"]
        o_end = min(w["end"], audio_dur)
        if o_end <= o_start:
            continue
        chunk = audio_wav[int(o_start * sample_rate):int(o_end * sample_rate)]
        h_end = cursor + len(chunk) / sample_rate
        segment_map.append((cursor, h_end, o_start, o_end))
        chunks.append(chunk)
        cursor = h_end

    hosts_wav = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
    return hosts_wav, segment_map


def map_to_original(diar_segments: list[dict], segment_map: list) -> list[dict]:
    """Convert hosts-only timestamps back to original audio timestamps."""
    result = []
    for seg in diar_segments:
        hs, he = seg["start"], seg["end"]
        for (mhs, mhe, orig_s, _orig_e) in segment_map:
            if he <= mhs or hs >= mhe:
                continue
            ovl_s = max(hs, mhs)
            ovl_e = min(he, mhe)
            offset = orig_s - mhs
            result.append({"start": ovl_s + offset,
                            "end":   ovl_e + offset,
                            "speaker": seg["speaker"]})
    return result


# --------------------------------------------------------------------------
# Speaker identification from anchors
# --------------------------------------------------------------------------
def identify_hosts(windows: list[dict], diar_segments: list[dict]) -> dict[str, str]:
    """
    Find SPEAKER_XX → 'Mr. Mamen' / 'Sigve' mapping from anchor chapters.
    Returns {speaker_id: name, ...}.
    """
    speaker_map: dict[str, str] = {}
    for w in windows:
        if w["category"] not in ("mamen_anchor", "sigve_anchor"):
            continue
        spk = speaker_for_range(diar_segments, w["start"], w["end"])
        if spk:
            name = w["label"]
            if spk not in speaker_map:
                speaker_map[spk] = name
                print(f"  Anchor '{w['title']}' → {spk} = {name}")
            elif speaker_map[spk] != name:
                print(f"  WARN: {spk} already mapped to {speaker_map[spk]}, "
                      f"anchor '{w['title']}' says {name}")
    return speaker_map


# --------------------------------------------------------------------------
# VTT relabeling
# --------------------------------------------------------------------------
def relabel_vtt(vtt_path: Path, windows: list[dict],
                diar_segments: list[dict], host_map: dict[str, str]) -> None:
    corrections = load_corrections()
    lines = vtt_path.read_text(encoding="utf-8").splitlines()
    out = []
    i = 0
    changed = 0
    while i < len(lines):
        line = lines[i]
        ts_m = re.match(r"(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})", line)
        if ts_m:
            cue_start = t2s(ts_m.group(1))
            cue_end = t2s(ts_m.group(2))
            out.append(line)
            i += 1
            if i < len(lines):
                text = lines[i]
                text = re.sub(r"^<v [^>]+>", "", text)  # strip existing tag
                i += 1

                # Determine label
                win = category_for_time(windows, cue_start)
                if win and win["category"] in ("caller", "overvakerne",
                                               "mamen_anchor", "sigve_anchor"):
                    label = win["label"]
                else:
                    # Regular or unmatched: use diarization
                    spk = speaker_for_range(diar_segments, cue_start, cue_end)
                    label = host_map.get(spk) if spk else None
                label = display_name(label, corrections)

                out.append(f"<v {label}>{text}" if label else text)
                changed += 1
        else:
            out.append(line)
            i += 1

    vtt_path.write_text("\n".join(out), encoding="utf-8")
    print(f"  Written {vtt_path}  ({changed} cues relabeled)")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--chapters", type=Path, required=True,
                        help="Episode chapters JSON file")
    parser.add_argument("--apply-to-vtt", type=Path, required=True,
                        help="VTT file to relabel in-place")
    parser.add_argument("--speakers", type=int, default=2,
                        help="Speaker count hint for pyannote (default: 2)")
    parser.add_argument("--diarization-model", default=DEFAULT_DIARIZATION_MODEL)
    parser.add_argument("--no-exclusive", action="store_true",
                        help="Use raw overlapping diarization output")
    parser.add_argument("--hosts-only", action="store_true",
                        help="Diarize only host segments (strip callers/Overvåkerne from "
                             "audio before diarizing — helps separate similar-sounding hosts)")
    parser.add_argument("--profiles", type=Path,
                        help="Speaker profiles .npy file built with build_speaker_profiles.py. "
                             "Used instead of (or as fallback from) anchor chapters.")
    parser.add_argument("--profile-threshold", type=float, default=PROFILE_THRESHOLD)
    parser.add_argument("--env", type=Path)
    args = parser.parse_args()

    root = project_root()
    hf_token = load_hf_token(args.env)
    if not hf_token:
        sys.stderr.write("HF_TOKEN not set\n")
        return 1

    # Load and categorize chapters
    chapters = json.loads(args.chapters.read_text(encoding="utf-8"))["chapters"]
    known_names = load_known_names(root)
    windows = categorize_chapters(chapters, known_names)

    print(f"\nChapter windows ({len(windows)} total):")
    for w in windows:
        if w["category"] != "regular":
            print(f"  [{format_ts(w['start'])}] {w['category']:12s}  {w['title']}")

    anchors = [w for w in windows if w["category"] in ("mamen_anchor", "sigve_anchor")]
    if not anchors:
        print("\nWARN: No anchor chapters found — cannot auto-identify hosts.")
        print("  Add chapters like 'MrMamen kårer...' or 'Sigve kårer...' to chapters JSON,")
        print("  or the script will label all regular cues without speaker names.")

    # Load audio + run diarization
    print(f"\nDecoding {args.audio.name}...")
    t0 = time.time()
    wav = load_audio(args.audio)
    print(f"  {len(wav)/16000/60:.1f} min decoded in {time.time()-t0:.1f}s")

    segment_map = None
    if args.hosts_only:
        print("Extracting host-only audio (stripping callers/Overvåkerne)...")
        diar_wav, segment_map = extract_host_audio(wav, windows)
        print(f"  Host audio: {len(diar_wav)/16000/60:.1f} min "
              f"(was {len(wav)/16000/60:.1f} min)")
    else:
        diar_wav = wav

    pipeline = load_diarization_pipeline(hf_token, args.diarization_model)
    raw_segments = run_diarization(pipeline, diar_wav, num_speakers=args.speakers,
                                   exclusive=not args.no_exclusive)

    if segment_map is not None:
        diar_segments = map_to_original(raw_segments, segment_map)
        print(f"  Mapped {len(raw_segments)} → {len(diar_segments)} segments "
              f"back to original timestamps")
    else:
        diar_segments = raw_segments

    # Identify hosts — try anchor chapters first, fall back to profiles
    print("\nIdentifying hosts from anchor chapters...")
    host_map = identify_hosts(windows, diar_segments)

    if len(host_map) < 2 and args.profiles:
        print(f"\nAnchor identification incomplete ({len(host_map)}/2 hosts). "
              f"Trying voice profiles...")
        host_map = match_profiles(diar_segments, wav, pipeline, args.profiles,
                                  threshold=args.profile_threshold)

    if len(host_map) < 2:
        print(f"  WARN: Only identified {len(host_map)} host(s) — "
              f"cannot reliably distinguish hosts.")
        print("  Regular cues will get no speaker tag (only anchors/callers/Overvåkerne labeled).")
        host_map = {}  # clear map so regular cues get no wrong label

    # Relabel VTT
    print(f"\nRelabeling {args.apply_to_vtt}...")
    relabel_vtt(args.apply_to_vtt, windows, diar_segments, host_map)

    # Summary
    print("\nFinal speaker distribution:")
    content = args.apply_to_vtt.read_text(encoding="utf-8")
    tags = re.findall(r"<v ([^>]+)>", content)
    no_tag = len(re.findall(r"^\d{2}:\d{2}:\d{2}", content, re.MULTILINE)) - len(tags)
    for name, count in Counter(tags).most_common():
        print(f"  {name}: {count}")
    if no_tag > 0:
        print(f"  (no tag): {no_tag}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
