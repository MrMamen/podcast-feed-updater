#!/usr/bin/env python3
"""Build speaker profiles from clean multitrack recordings.

Unlike build_speaker_profiles.py which needs a labelled VTT, this script
assumes each input audio file contains a SINGLE speaker only (typical for
multi-track podcast recordings where each speaker has their own mic).

Strategy:
  1. Split each track into overlapping windows (default 8s, 4s hop)
  2. Skip windows below an energy threshold (silence)
  3. Compute embedding per window
  4. Mean-pool embeddings across all files for each speaker
  5. L2-normalise and save profile

Usage:
    uv run python scripts/build_profiles_clean.py --config <path-to-config.json> \\
        -o <output.npy>

The config file maps speaker labels to a list of clean audio tracks. Both
the labels and the file paths are private to your local setup — keep this
config outside version control. See README for an example schema.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from asr_common import (
    DEFAULT_DIARIZATION_MODEL,
    embed_chunk,
    embedding_model,
    load_audio,
    load_diarization_pipeline,
    load_hf_token,
    load_profiles,
    save_profiles,
    setup_cuda_paths,
)

setup_cuda_paths()


def windows_with_voice(wav, sample_rate=16000, win_s=8.0, hop_s=4.0,
                       energy_db_floor=-40.0, max_windows: int | None = None):
    """Overlapping windows above an energy floor.

    Energy floor is dB relative to the file's peak — windows quieter than
    this are skipped (silence, breath gaps). -40 dB is conservative.
    """
    import numpy as np
    win_n = int(win_s * sample_rate)
    hop_n = int(hop_s * sample_rate)
    peak = float(np.max(np.abs(wav)) + 1e-8)
    floor_amp = peak * (10 ** (energy_db_floor / 20.0))
    out = []
    for start in range(0, len(wav) - win_n + 1, hop_n):
        chunk = wav[start:start + win_n]
        rms = float(np.sqrt(np.mean(chunk * chunk)))
        if rms < floor_amp:
            continue
        out.append((start / sample_rate, chunk))
        if max_windows and len(out) >= max_windows:
            break
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", type=Path, required=True,
                        help='JSON: {"Name": ["track1.wav", ...]}')
    parser.add_argument("-o", "--output", type=Path,
                        default=Path("transcripts/speaker_profiles.npy"),
                        help="Output .npy profile file")
    parser.add_argument("--win-seconds", type=float, default=8.0)
    parser.add_argument("--hop-seconds", type=float, default=4.0)
    parser.add_argument("--max-windows-per-file", type=int, default=80,
                        help="Cap windows per file to avoid runaway runtime")
    parser.add_argument("--energy-floor-db", type=float, default=-40.0,
                        help="Skip windows below this RMS dB relative to peak")
    parser.add_argument("--merge", action="store_true",
                        help="Merge with existing profile file instead of overwriting")
    parser.add_argument("--diarization-model", default=DEFAULT_DIARIZATION_MODEL,
                        help="Pipeline whose embedding model to use")
    parser.add_argument("--env", type=Path)
    args = parser.parse_args()

    hf_token = load_hf_token(args.env)
    if not hf_token:
        sys.stderr.write("HF_TOKEN not set in .env\n")
        return 1

    config = json.loads(args.config.read_text())
    print(f"Building profiles for {len(config)} speakers")
    for name, paths in config.items():
        print(f"  {name}: {len(paths)} track(s)")

    import numpy as np

    pipeline = load_diarization_pipeline(hf_token, args.diarization_model)
    emb_model = embedding_model(pipeline)
    print(f"  embedding dim={emb_model.dimension}, sr={emb_model.sample_rate}")

    profiles: dict[str, np.ndarray] = {}
    for name, paths in config.items():
        print(f"\n=== {name} ===")
        all_embs = []
        for p in paths:
            p_path = Path(p)
            if not p_path.exists():
                print(f"  ⚠ skipping (not found): {p}")
                continue
            print(f"  loading {p_path.name}...")
            t0 = time.time()
            wav = load_audio(p_path)
            wins = windows_with_voice(
                wav, win_s=args.win_seconds, hop_s=args.hop_seconds,
                energy_db_floor=args.energy_floor_db,
                max_windows=args.max_windows_per_file,
            )
            print(f"    {len(wav)/16000/60:.1f} min decoded, "
                  f"{len(wins)} usable windows ({time.time()-t0:.1f}s)")
            dropped = 0
            for _ts, chunk in wins:
                emb = embed_chunk(emb_model, chunk)
                if emb is None:
                    dropped += 1
                    continue
                all_embs.append(emb)
            if dropped:
                print(f"    ⚠ dropped {dropped} NaN/failed window(s)")
        if not all_embs:
            print(f"  ✗ no embeddings extracted for {name}")
            continue
        mean = np.mean(all_embs, axis=0)
        mean /= np.linalg.norm(mean) + 1e-8
        profiles[name] = mean
        print(f"  {name}: {len(all_embs)} embeddings averaged")

    if args.merge and args.output.exists():
        print(f"\nMerging with existing {args.output}...")
        existing = load_profiles(args.output)
        for name in existing:
            if name not in profiles:
                profiles[name] = existing[name]
                print(f"  kept existing: {name}")

    save_profiles(profiles, args.output)
    print(f"\n✓ Saved {len(profiles)} profiles to {args.output}")

    if len(profiles) >= 2:
        print("\nCross-speaker similarities (should be < 0.5 for distinct):")
        names = list(profiles)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                sim = float(np.dot(profiles[names[i]], profiles[names[j]]))
                flag = "✓" if sim < 0.5 else ("⚠" if sim < 0.7 else "⚠⚠ HIGH")
                print(f"  {names[i]} ↔ {names[j]}: {sim:.3f}  {flag}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
