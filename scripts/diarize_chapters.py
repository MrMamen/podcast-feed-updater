#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pyannote.audio>=4.0",
#     "python-dotenv>=1.0",
#     "av>=13",
#     "torch",
#     "numpy",
# ]
# ///
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
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path


# --------------------------------------------------------------------------
# CUDA path setup (same pattern as transcribe.py)
# --------------------------------------------------------------------------
def _setup_cuda_paths() -> None:
    script_dir = Path(__file__).resolve().parent
    venv_site = script_dir.parent / ".venv" / "lib" / "python3.12" / "site-packages" / "nvidia"
    if not venv_site.exists():
        return
    paths = []
    for sub in ("cu13/lib", "cublas/lib", "cudnn/lib", "cuda_nvrtc/lib"):
        p = venv_site / sub
        if p.exists():
            paths.append(str(p))
    if not paths:
        return
    existing = os.environ.get("LD_LIBRARY_PATH", "")
    existing_set = set(existing.split(":")) if existing else set()
    if all(p in existing_set for p in paths):
        return
    new_ld = ":".join(paths + ([existing] if existing else []))
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = new_ld
    os.execve(sys.executable, [sys.executable] + sys.argv, env)


_setup_cuda_paths()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def format_ts(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def t2s(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def load_audio(path: str, sample_rate: int = 16000):
    import av
    import numpy as np
    container = av.open(path)
    resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)
    chunks = []
    for frame in container.decode(audio=0):
        for r in resampler.resample(frame):
            chunks.append(r.to_ndarray())
    container.close()
    wav = np.concatenate(chunks, axis=-1).astype(np.float32) / 32768.0
    if wav.ndim == 2:
        wav = wav[0]
    return wav


# --------------------------------------------------------------------------
# Chapter categorization
# --------------------------------------------------------------------------


def load_known_names(project_root: Path) -> set[str]:
    """Load all guest names + aliases from cdspill_known_guests.json."""
    path = project_root / "cdspill_known_guests.json"
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
        for (mhs, mhe, os, oe) in segment_map:
            if he <= mhs or hs >= mhe:
                continue
            ovl_s = max(hs, mhs)
            ovl_e = min(he, mhe)
            offset = os - mhs
            result.append({"start": ovl_s + offset,
                            "end":   ovl_e + offset,
                            "speaker": seg["speaker"]})
    return result


# --------------------------------------------------------------------------
# Diarization
# --------------------------------------------------------------------------
def run_diarization(audio_wav, *, num_speakers: int, hf_token: str) -> list[dict]:
    import torch
    from pyannote.audio import Pipeline

    print("Loading pyannote pipeline...")
    t0 = time.time()
    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=hf_token)
    pipeline.to(torch.device("cuda"))
    print(f"  loaded in {time.time()-t0:.1f}s")

    print(f"Running diarization (hint: {num_speakers} speakers)...")
    t0 = time.time()
    waveform = torch.from_numpy(audio_wav).unsqueeze(0)
    result = pipeline({"waveform": waveform, "sample_rate": 16000},
                      num_speakers=num_speakers)
    ann = result.speaker_diarization if hasattr(result, "speaker_diarization") else result
    elapsed = time.time() - t0

    segments = []
    for turn, _, spk in ann.itertracks(yield_label=True):
        segments.append({"start": turn.start, "end": turn.end, "speaker": spk})

    totals: dict[str, float] = defaultdict(float)
    for s in segments:
        totals[s["speaker"]] += s["end"] - s["start"]
    dur = len(audio_wav) / 16000
    print(f"\n  {len({s['speaker'] for s in segments})} speakers, "
          f"{len(segments)} turns in {elapsed:.1f}s")
    for spk in sorted(totals, key=lambda x: -totals[x]):
        print(f"    {spk}: {totals[spk]/60:.1f} min ({totals[spk]/dur*100:.0f}%)")

    return segments, pipeline


def speaker_for_range(segments: list[dict], start: float, end: float) -> str | None:
    overlap: dict[str, float] = defaultdict(float)
    for s in segments:
        if s["end"] < start or s["start"] > end:
            continue
        ovl = min(s["end"], end) - max(s["start"], start)
        if ovl > 0:
            overlap[s["speaker"]] += ovl
    return max(overlap, key=overlap.get) if overlap else None


def dominant_speaker_in_window(segments: list[dict], start: float, end: float) -> str | None:
    """Which diarization speaker dominates the [start, end] window?"""
    overlap: dict[str, float] = defaultdict(float)
    for s in segments:
        if s["end"] < start or s["start"] > end:
            continue
        ovl = min(s["end"], end) - max(s["start"], start)
        if ovl > 0:
            overlap[s["speaker"]] += ovl
    return max(overlap, key=overlap.get) if overlap else None


# --------------------------------------------------------------------------
# Profile-based speaker identification
# --------------------------------------------------------------------------
def identify_hosts_from_profiles(
    diar_segments: list[dict],
    audio_wav,
    pipeline,
    profiles_path: Path,
    *,
    sample_rate: int = 16000,
    threshold: float = 0.5,
) -> dict[str, str]:
    """
    Match each SPEAKER_XX cluster against saved voice profiles.
    Returns {speaker_id: name} for confident matches (similarity > threshold).
    """
    import numpy as np
    import torch

    profiles: dict[str, np.ndarray] = np.load(profiles_path, allow_pickle=True).item()
    emb_model = pipeline._embedding

    # Group diarization segments by speaker
    by_speaker: dict[str, list] = defaultdict(list)
    for seg in diar_segments:
        by_speaker[seg["speaker"]].append(seg)

    speaker_map: dict[str, str] = {}
    print(f"Matching {len(by_speaker)} diarization clusters against "
          f"{len(profiles)} profiles...")

    for spk, segs in sorted(by_speaker.items()):
        # Sample up to 30 of the longest segments to build cluster embedding
        min_s = emb_model.min_num_samples
        long_segs = sorted(segs, key=lambda s: s["end"] - s["start"], reverse=True)
        sample_segs = long_segs[:30]
        embs = []
        for seg in sample_segs:
            s_idx = int(seg["start"] * sample_rate)
            e_idx = int(seg["end"] * sample_rate)
            min_s = emb_model.min_num_samples
            if e_idx - s_idx < min_s:
                continue
            chunk = audio_wav[s_idx:e_idx]
            try:
                t = torch.from_numpy(chunk).unsqueeze(0).unsqueeze(0)
                emb = np.array(emb_model(t)[0])
                embs.append(emb)
            except Exception:
                continue
        if not embs:
            continue

        cluster_emb = np.mean(embs, axis=0)
        cluster_emb /= np.linalg.norm(cluster_emb) + 1e-8

        # Compare against all profiles
        sims = {}
        for name, prof_emb in profiles.items():
            sim = float(np.dot(cluster_emb, prof_emb))
            sims[name] = sim

        best_name = max(sims, key=sims.get)
        best_sim = sims[best_name]

        sim_str = "  ".join(f"{n}={v:.3f}" for n, v in sorted(sims.items()))
        if best_sim >= threshold:
            speaker_map[spk] = best_name
            print(f"  {spk} → {best_name} (sim={best_sim:.3f})  [{sim_str}]")
        else:
            print(f"  {spk} → no match (best {best_name}={best_sim:.3f} < {threshold})  [{sim_str}]")

    return speaker_map


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
        spk = dominant_speaker_in_window(diar_segments, w["start"], w["end"])
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
                if win and win["category"] in ("caller", "overvakerne"):
                    label = win["label"]
                elif win and win["category"] in ("mamen_anchor", "sigve_anchor"):
                    label = win["label"]
                else:
                    # Regular or unmatched: use diarization
                    spk = speaker_for_range(diar_segments, cue_start, cue_end)
                    label = host_map.get(spk) if spk else None

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
    import argparse
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--chapters", type=Path, required=True,
                        help="Episode chapters JSON file")
    parser.add_argument("--apply-to-vtt", type=Path, required=True,
                        help="VTT file to relabel in-place")
    parser.add_argument("--speakers", type=int, default=2,
                        help="Speaker count hint for pyannote (default: 2)")
    parser.add_argument("--hosts-only", action="store_true",
                        help="Diarize only host segments (strip callers/Overvåkerne from "
                             "audio before diarizing — helps separate similar-sounding hosts)")
    parser.add_argument("--profiles", type=Path,
                        help="Speaker profiles .npy file built with build_speaker_profiles.py. "
                             "Used instead of (or as fallback from) anchor chapters.")
    parser.add_argument("--env", type=Path)
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    env_path = args.env or (project_root / ".env")
    if env_path.exists():
        from dotenv import load_dotenv
        load_dotenv(env_path)
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        sys.stderr.write("HF_TOKEN not set\n")
        return 1

    # Load and categorize chapters
    chapters = json.loads(args.chapters.read_text(encoding="utf-8"))["chapters"]
    known_names = load_known_names(project_root)
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
    wav = load_audio(str(args.audio))
    print(f"  {len(wav)/16000/60:.1f} min decoded in {time.time()-t0:.1f}s")

    segment_map = None
    if args.hosts_only:
        print("Extracting host-only audio (stripping callers/Overvåkerne)...")
        diar_wav, segment_map = extract_host_audio(wav, windows)
        print(f"  Host audio: {len(diar_wav)/16000/60:.1f} min "
              f"(was {len(wav)/16000/60:.1f} min)")
    else:
        diar_wav = wav

    raw_segments, pipeline = run_diarization(diar_wav, num_speakers=args.speakers,
                                              hf_token=hf_token)

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
        host_map = identify_hosts_from_profiles(
            diar_segments, wav, pipeline, args.profiles,
        )

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
    from collections import Counter
    import re as _re
    content = args.apply_to_vtt.read_text(encoding="utf-8")
    tags = _re.findall(r"<v ([^>]+)>", content)
    no_tag = len(_re.findall(r"^\d{2}:\d{2}:\d{2}", content, _re.MULTILINE)) - len(tags)
    for name, count in Counter(tags).most_common():
        print(f"  {name}: {count}")
    if no_tag > 0:
        print(f"  (no tag): {no_tag}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
