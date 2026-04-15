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
"""Quick diarization diagnostic — no transcription, just speaker stats."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path


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


def format_ts(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


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


def speaker_for_range(segments: list, start: float, end: float) -> str | None:
    """Speaker with most overlap in [start, end]."""
    from collections import defaultdict
    overlap: dict[str, float] = defaultdict(float)
    for s in segments:
        if s["end"] < start or s["start"] > end:
            continue
        ovl = min(s["end"], end) - max(s["start"], start)
        if ovl > 0:
            overlap[s["speaker"]] += ovl
    return max(overlap, key=overlap.get) if overlap else None


def t2s(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def apply_to_vtt(vtt_path: Path, segments: list, speaker_map: dict[str, str]) -> None:
    """Re-label an existing VTT with diarization segments."""
    import re
    lines = vtt_path.read_text(encoding="utf-8").splitlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Detect timestamp line
        ts_match = re.match(r"(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})", line)
        if ts_match:
            start = t2s(ts_match.group(1))
            end = t2s(ts_match.group(2))
            out.append(line)
            i += 1
            # Next line is the text (possibly with existing <v ...> tag)
            if i < len(lines):
                text = lines[i]
                # Strip existing <v ...> tag
                text = re.sub(r"^<v [^>]+>", "", text)
                spk = speaker_for_range(segments, start, end)
                name = speaker_map.get(spk) if spk else None
                out.append(f"<v {name}>{text}" if name else text)
                i += 1
        else:
            out.append(line)
            i += 1
    vtt_path.write_text("\n".join(out), encoding="utf-8")
    print(f"  Updated {vtt_path}")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--speakers", type=int, help="Number of speakers hint")
    parser.add_argument("--speaker-map", type=str,
                        help='Apply names to existing VTT, e.g. "SPEAKER_02=Aleksikon". '
                             'Speakers not listed get no tag.')
    parser.add_argument("--apply-to-vtt", type=Path,
                        help="Existing VTT to relabel with diarization result")
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

    # Parse speaker map
    speaker_map: dict[str, str] = {}
    if args.speaker_map:
        for pair in args.speaker_map.split(","):
            k, _, v = pair.partition("=")
            speaker_map[k.strip()] = v.strip()

    import torch
    from pyannote.audio import Pipeline
    from collections import defaultdict

    print(f"Decoding {args.audio.name}...")
    t0 = time.time()
    wav = load_audio(str(args.audio))
    duration_min = len(wav) / 16000 / 60
    print(f"  {duration_min:.1f} min decoded in {time.time()-t0:.1f}s")

    print("Loading pyannote pipeline...")
    t0 = time.time()
    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=hf_token)
    pipeline.to(torch.device("cuda"))
    print(f"  loaded in {time.time()-t0:.1f}s")

    print(f"Running diarization{f' (hint: {args.speakers} speakers)' if args.speakers else ''}...")
    t0 = time.time()
    waveform = torch.from_numpy(wav).unsqueeze(0)
    kwargs = {}
    if args.speakers:
        kwargs["num_speakers"] = args.speakers
    result = pipeline({"waveform": waveform, "sample_rate": 16000}, **kwargs)
    ann = result.speaker_diarization if hasattr(result, "speaker_diarization") else result
    elapsed = time.time() - t0

    segments = []
    for turn, _, speaker in ann.itertracks(yield_label=True):
        segments.append({"start": turn.start, "end": turn.end, "speaker": speaker})

    speakers = sorted({s["speaker"] for s in segments})
    totals: dict[str, float] = defaultdict(float)
    for s in segments:
        totals[s["speaker"]] += s["end"] - s["start"]

    print(f"\n=== Diarization result ({elapsed:.1f}s) ===")
    print(f"  {len(speakers)} speakers detected, {len(segments)} turns")
    print()
    for spk in sorted(totals, key=lambda x: -totals[x]):
        pct = totals[spk] / (duration_min * 60) * 100
        print(f"  {spk}: {totals[spk]/60:.1f} min ({pct:.0f}%)")

    print("\n=== First 5 turns per speaker ===")
    seen: dict[str, int] = {}
    for seg in segments:
        spk = seg["speaker"]
        if seen.get(spk, 0) >= 5:
            continue
        seen[spk] = seen.get(spk, 0) + 1
        print(f"  {spk} {format_ts(seg['start'])} → {format_ts(seg['end'])}  "
              f"({seg['end']-seg['start']:.1f}s)")

    if args.apply_to_vtt and speaker_map:
        print(f"\nRelabeling {args.apply_to_vtt}...")
        apply_to_vtt(args.apply_to_vtt, segments, speaker_map)

    return 0


if __name__ == "__main__":
    sys.exit(main())
