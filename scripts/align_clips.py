#!/usr/bin/env python3
"""Tag and transcribe pre-recorded listener clips by locating them in the mix.

"Spillåret" episodes splice in a dozen listener contributions that were
recorded separately. Diarising sixteen voices in a 150 min mix is
unreliable, and tagging by chapter start is wrong whenever the hosts talk
around a clip. When the original clip files are in the episode folder,
this script instead finds each clip inside the mix by normalised
cross-correlation of log-band energy features (robust to gain, EQ and a
music bed), then rewrites the raw cache from `transcribe.py` so that

  * the clip's speech span carries one diarization turn with the
    contributor's name,
  * the mix transcript inside that span is replaced by a transcript of the
    clean clip (transcribe.py --no-diarization, run here when missing),
  * clusters that only spoke inside clips lose any stray turns elsewhere,
    and the guessed "guest from metadata" names are dropped.

Then re-render with `transcribe.py -o <vtt> --render-only`.

Usage:
    uv run python scripts/align_clips.py -o transcripts/1995.vtt --episode-number 125 \\
        --clip "1995 - ALEKSIKON.wav=Aleksikon" --clip "DrBoble 1995.m4a=Anette Vik Jøsendal" ...
    uv run python scripts/align_clips.py -o transcripts/1995.vtt --episode-number 125 --clips clips.json

`--clips` is a JSON object {filename: speaker}. Filenames are relative to
the episode folder (NFC/NFD spelling differences are tolerated). Use the
full profile-style name; the VTT gets the short form as usual. A song or a
character voice gets the name it should be tagged with ("Punti", "Kato").
`--language en` on a clip: append `|en` to the speaker ("Punti|en") so the
clean clip is transcribed in English instead of being translated.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

import numpy as np

from asr_common import (
    DEFAULT_AUDIO_LIBRARY,
    SAMPLE_RATE,
    find_episode_audio,
    format_ts,
    load_audio,
)

HOP = 320            # 20 ms frames
NFFT = 1024
NBANDS = 40
FPS = SAMPLE_RATE / HOP
HOSTS = {"Mr. Mamen", "Sigve"}


# --------------------------------------------------------------------------
# Features and matching
# --------------------------------------------------------------------------
def _band_edges():
    freqs = np.fft.rfftfreq(NFFT, 1 / SAMPLE_RATE)
    idx = np.searchsorted(freqs, np.geomspace(100, 7000, NBANDS + 1))
    return [(idx[i], max(idx[i] + 1, idx[i + 1])) for i in range(NBANDS)]


_EDGES = _band_edges()
_WIN = np.hanning(NFFT).astype(np.float32)


def features(wav: np.ndarray) -> np.ndarray:
    """Mean-removed log energy in NBANDS log-spaced bands, 50 fps."""
    n = (len(wav) - NFFT) // HOP + 1
    if n <= 0:
        return np.zeros((NBANDS, 0), np.float32)
    frames = np.lib.stride_tricks.as_strided(
        wav, shape=(n, NFFT), strides=(wav.strides[0] * HOP, wav.strides[0]))
    out = np.empty((NBANDS, n), np.float32)
    for s in range(0, n, 20000):
        spec = np.abs(np.fft.rfft(frames[s:s + 20000] * _WIN, axis=1)) ** 2
        for b, (lo, hi) in enumerate(_EDGES):
            out[b, s:s + 20000] = spec[:, lo:hi].sum(axis=1)
    out = np.log(out + 1e-6)
    out -= out.mean(axis=1, keepdims=True)
    return out


def ncc(mix_f: np.ndarray, win_f: np.ndarray) -> np.ndarray:
    """Normalised cross-correlation of a feature window along the mix."""
    from scipy.signal import fftconvolve

    nb, L = win_f.shape
    w = win_f - win_f.mean(axis=1, keepdims=True)
    num = np.zeros(mix_f.shape[1] - L + 1)
    for b in range(nb):
        num += fftconvolve(mix_f[b], w[b][::-1], mode="valid")
    ones = np.ones(L)
    m_sum = np.stack([fftconvolve(mix_f[b], ones, mode="valid") for b in range(nb)])
    m_sq = np.stack([fftconvolve(mix_f[b] ** 2, ones, mode="valid") for b in range(nb)])
    var = (m_sq - m_sum ** 2 / L).sum(axis=0)
    return num / np.sqrt(np.maximum(var, 1e-6) * (w ** 2).sum())


def locate(mix_f: np.ndarray, clip: np.ndarray, *, win_s: float = 6.0,
           step_s: float = 8.0) -> dict | None:
    """Offset of the clip in the mix (seconds), or None when not found.

    Several windows of the clip are matched independently; the median of
    the confident offsets wins, and the number of agreeing windows says
    whether the clip was inserted whole.
    """
    clip_f = features(clip)
    dur = len(clip) / SAMPLE_RATE
    L = int(win_s * FPS)
    hits = []
    t = 0.0
    while t + win_s <= dur + 1e-6:
        wf = clip_f[:, int(t * FPS):int(t * FPS) + L]
        if wf.shape[1] < L:
            break
        if wf.std() >= 0.5:          # skip near-silent windows
            c = ncc(mix_f, wf)
            k = int(np.argmax(c))
            peak = float(c[k])
            c[max(0, k - 100):k + 100] = -1
            hits.append((t, k / FPS - t, peak, float(c.max())))
        t += step_s
    good = [h for h in hits if h[2] > 0.5 and h[2] - h[3] > 0.1]
    if not good:
        return None
    med = float(np.median([h[1] for h in good]))
    agree = [h for h in hits if abs(h[1] - med) < 0.2]
    return {"offset": med, "duration": dur, "windows": len(hits), "agree": len(agree),
            "peak_min": min(h[2] for h in agree), "peak_max": max(h[2] for h in agree)}


# --------------------------------------------------------------------------
# Raw-cache merge
# --------------------------------------------------------------------------
def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def resolve(folder: Path, fname: str) -> Path | None:
    p = folder / fname
    if p.exists():
        return p
    for cand in folder.iterdir():
        if _nfc(cand.name) == _nfc(fname):
            return cand
    return None


def cut_turns(turns: list[dict], lo: float, hi: float) -> list[dict]:
    out = []
    for d in turns:
        if d["end"] <= lo or d["start"] >= hi:
            out.append(d)
            continue
        if d["start"] < lo:
            out.append({**d, "end": lo})
        if d["end"] > hi:
            out.append({**d, "start": hi})
    return out


def trim_segment(seg: dict, lo: float, hi: float) -> dict | None:
    """Drop the words whose midpoint falls inside [lo, hi]."""
    words = [w for w in seg["words"] if not (lo <= (w["start"] + w["end"]) / 2 <= hi)]
    if not words:
        return None
    if len(words) == len(seg["words"]):
        return seg
    return {**seg, "start": words[0]["start"], "end": words[-1]["end"],
            "text": "".join(w["word"] for w in words).strip(), "words": words}


def merge(raw: dict, placements: list[dict], pad: float = 0.3) -> dict:
    segs, diar = raw["segments"], raw["diarization"] or []
    smap = dict(raw.get("speaker_map") or {})
    spans = []
    for p in sorted(placements, key=lambda x: x["mix_start"]):
        who, off, clip_raw = p["speaker"], p["offset"], p["clip_raw"]
        words = [w for s in clip_raw["segments"] for w in s["words"]]
        if not words:
            print(f"  {who}: clip transcript has no words, skipping")
            continue
        lo, hi = words[0]["start"] + off - pad, words[-1]["end"] + off + pad
        spans.append((lo, hi))
        diar = cut_turns(diar, lo, hi) + [{"start": lo, "end": hi, "speaker": who}]
        smap[who] = who
        kept = []
        for s in segs:
            if s["end"] <= lo or s["start"] >= hi:
                kept.append(s)
            elif (t := trim_segment(s, lo, hi)) is not None:
                kept.append(t)
        added = [{"start": s["start"] + off, "end": s["end"] + off, "text": s["text"],
                  "words": [{**w, "start": w["start"] + off, "end": w["end"] + off}
                            for w in s["words"]],
                  "gap": s.get("gap", False), "from_clip": who}
                 for s in clip_raw["segments"]]
        touched = len(segs) - len(kept)
        segs = kept + added
        print(f"  {who:22s} {format_ts(lo)} - {format_ts(hi)}  "
              f"{len(added)} clip segments in, {touched} mix segments dropped or trimmed")
    segs.sort(key=lambda s: s["start"])
    diar.sort(key=lambda d: d["start"])

    clip_names = {p["speaker"] for p in placements}

    def inside(d):
        return any(min(d["end"], hi) - max(d["start"], lo) > 0 for lo, hi in spans)

    n = len(diar)
    diar = [d for d in diar if smap.get(d["speaker"], d["speaker"]) in HOSTS
            or d["speaker"] in clip_names or inside(d)]
    for k in [k for k in smap if k.startswith("SPEAKER_") and smap[k] not in HOSTS]:
        del smap[k]
    print(f"  dropped {n - len(diar)} stray turns of clip-only clusters; "
          f"host clusters: { {k: v for k, v in smap.items() if k.startswith('SPEAKER_')} }")
    return {**raw, "segments": segs, "diarization": diar, "speaker_map": smap}


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
    ap.add_argument("--clip", action="append", default=[],
                    help='"<file in episode folder>=<Speaker>" (repeatable)')
    ap.add_argument("--clips", type=Path, help="JSON {file: speaker}")
    ap.add_argument("--locate-only", action="store_true",
                    help="Print where the clips are in the mix and stop")
    ap.add_argument("--no-transcribe", action="store_true",
                    help="Fail instead of transcribing clips whose raw cache is missing")
    args = ap.parse_args()

    project = Path(__file__).resolve().parent.parent
    mapping: dict[str, str] = {}
    if args.clips:
        mapping.update(json.loads(args.clips.read_text(encoding="utf-8")))
    for item in args.clip:
        f, _, who = item.partition("=")
        mapping[f.strip()] = who.strip()
    if not mapping:
        sys.stderr.write("Give at least one --clip FILE=Speaker or --clips JSON.\n")
        return 1

    mix_path = find_episode_audio(args.episode_number, args.library)
    folder = mix_path.parent
    print(f"Decoding mix {mix_path.name}...")
    mix_f = features(load_audio(mix_path))

    placements = []
    for fname, who in mapping.items():
        who, _, lang = who.partition("|")
        path = resolve(folder, fname)
        if path is None:
            print(f"  ⚠ {fname}: not found in {folder}")
            continue
        loc = locate(mix_f, load_audio(path))
        if loc is None:
            print(f"  ✗ {who:22s} {path.name}: not found in the mix")
            continue
        flag = "" if loc["agree"] == loc["windows"] else \
            f"  ⚠ only {loc['agree']}/{loc['windows']} windows agree (clip edited?)"
        print(f"  {who:22s} {path.name}: mix {format_ts(loc['offset'])} - "
              f"{format_ts(loc['offset'] + loc['duration'])}  "
              f"(ncc {loc['peak_min']:.2f}-{loc['peak_max']:.2f}){flag}")
        placements.append({"file": path, "speaker": who, "lang": lang or "no",
                           "offset": loc["offset"], "mix_start": loc["offset"],
                           "mix_end": loc["offset"] + loc["duration"]})
    if args.locate_only or not placements:
        return 0

    raw_dir = project / ".cache" / "raw"
    for p in placements:
        cache = raw_dir / (p["file"].stem + ".json")
        if not cache.exists():
            if args.no_transcribe:
                sys.stderr.write(f"Missing {cache}; run transcribe.py --no-diarization on it.\n")
                return 1
            print(f"Transcribing clean clip {p['file'].name}...")
            cmd = [sys.executable, str(project / "scripts" / "transcribe.py"), str(p["file"]),
                   "-o", str(raw_dir / (p["file"].stem + ".clip.vtt")), "--no-diarization",
                   "--episode-number", str(args.episode_number), "--language", p["lang"]]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode:
                sys.stderr.write(r.stderr[-1500:])
                return 1
            cache = raw_dir / (p["file"].stem + ".clip.json")
        p["clip_raw"] = json.loads(cache.read_text(encoding="utf-8"))

    raw_path = raw_dir / (args.output.stem + ".json")
    if not raw_path.exists():
        sys.stderr.write(f"No raw cache {raw_path}; run transcribe.py -o {args.output} first.\n")
        return 1
    orig = raw_path.with_suffix(".orig.json")
    if not orig.exists():
        shutil.copy(raw_path, orig)
    print(f"Merging into {raw_path.relative_to(project)} (from {orig.name})...")
    raw = merge(json.loads(orig.read_text(encoding="utf-8")), placements)
    raw_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    print(f"Done. Re-render with:\n  uv run python scripts/transcribe.py -o {args.output} --render-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
