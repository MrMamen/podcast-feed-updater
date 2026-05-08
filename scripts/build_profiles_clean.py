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
    scripts/build_profiles_clean.py --config <path-to-config.json> \\
        -o <output.npy>

The config file maps speaker labels to a list of clean audio tracks. Both
the labels and the file paths are private to your local setup — keep this
config outside version control. See README for an example schema.
"""
from __future__ import annotations

import argparse
import json
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
    if all(p in existing.split(":") for p in paths):
        return
    new_ld = ":".join(paths + ([existing] if existing else []))
    env = {k: v for k, v in os.environ.items() if not k.startswith("BASH_FUNC_")}
    env["LD_LIBRARY_PATH"] = new_ld
    os.execve(sys.executable, [sys.executable] + sys.argv, env)


_setup_cuda_paths()


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


def windows_with_voice(wav, sample_rate=16000, win_s=8.0, hop_s=4.0,
                      energy_db_floor=-40.0, max_windows: int | None = None):
    """Yield overlapping windows above an energy floor.

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
    parser.add_argument("--env", type=Path)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    env_path = args.env or (project_root / ".env")
    if env_path.exists():
        from dotenv import load_dotenv
        load_dotenv(env_path)
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        sys.stderr.write("HF_TOKEN not set in .env\n")
        return 1

    config = json.loads(args.config.read_text())
    print(f"Building profiles for {len(config)} speakers")
    for name, paths in config.items():
        print(f"  {name}: {len(paths)} track(s)")

    import numpy as np
    import torch
    from pyannote.audio import Pipeline

    print("\nLoading pyannote/speaker-diarization-3.1...")
    t0 = time.time()
    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=hf_token)
    pipeline.to(torch.device("cuda"))
    emb_model = pipeline._embedding
    print(f"  loaded in {time.time()-t0:.1f}s "
          f"(dim={emb_model.dimension}, sr={emb_model.sample_rate})")

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
            wav = load_audio(str(p_path))
            wins = windows_with_voice(
                wav, win_s=args.win_seconds, hop_s=args.hop_seconds,
                energy_db_floor=args.energy_floor_db,
                max_windows=args.max_windows_per_file,
            )
            print(f"    {len(wav)/16000/60:.1f} min decoded, "
                  f"{len(wins)} usable windows ({time.time()-t0:.1f}s)")
            nan_in_file = 0
            for _ts, chunk in wins:
                try:
                    t = torch.from_numpy(chunk).unsqueeze(0).unsqueeze(0)
                    emb = np.array(emb_model(t)[0])
                    # Drop NaN embeddings (can happen on silent windows even
                    # above energy floor if pooling-layer std() degenerates).
                    if np.isnan(emb).any():
                        nan_in_file += 1
                        continue
                    all_embs.append(emb)
                except Exception as e:
                    print(f"    skip window: {e}")
            if nan_in_file:
                print(f"    ⚠ dropped {nan_in_file} NaN window(s)")
        if not all_embs:
            print(f"  ✗ no embeddings extracted for {name}")
            continue
        mean = np.mean(all_embs, axis=0)
        mean /= np.linalg.norm(mean) + 1e-8
        profiles[name] = mean
        print(f"  {name}: {len(all_embs)} embeddings averaged")

    # Optional merge with existing profile file
    if args.merge and args.output.exists():
        print(f"\nMerging with existing {args.output}...")
        existing = np.load(args.output, allow_pickle=True).item()
        for name in existing:
            if name not in profiles:
                profiles[name] = existing[name]
                print(f"  kept existing: {name}")

    # Save
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.save(args.output, profiles)
    print(f"\n✓ Saved {len(profiles)} profiles to {args.output}")

    # Sanity check
    if len(profiles) >= 2:
        print("\nCross-speaker similarities (should be < 0.5 for distinct):")
        names = list(profiles.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                sim = float(np.dot(profiles[names[i]], profiles[names[j]]))
                flag = "✓" if sim < 0.5 else ("⚠" if sim < 0.7 else "⚠⚠ HIGH")
                print(f"  {names[i]} ↔ {names[j]}: {sim:.3f}  {flag}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
