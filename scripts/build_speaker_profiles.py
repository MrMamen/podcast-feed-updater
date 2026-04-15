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
"""Build speaker embedding profiles from a labeled VTT + audio file.

Extracts pyannote/embedding vectors for each speaker in the VTT and saves
the mean embedding per speaker to a .npy file. These profiles can then be
used by diarize_chapters.py to auto-identify known speakers in new episodes.

Usage:
    scripts/build_speaker_profiles.py audio.mp3 transcript.vtt \\
        -o transcripts/speaker_profiles.npy

    # Merge additional episodes into existing profiles:
    scripts/build_speaker_profiles.py audio2.mp3 transcript2.vtt \\
        -o transcripts/speaker_profiles.npy --merge
"""
from __future__ import annotations

import argparse
import json
import os
import re
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


def t2s(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_vtt_segments(vtt_path: Path) -> list[dict]:
    """Extract (start, end, speaker) from a labeled WebVTT file."""
    segments = []
    lines = vtt_path.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        ts_m = re.match(r"(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})", line)
        if ts_m:
            start = t2s(ts_m.group(1))
            end = t2s(ts_m.group(2))
            i += 1
            if i < len(lines):
                text_line = lines[i]
                spk_m = re.match(r"<v ([^>]+)>", text_line)
                if spk_m:
                    segments.append({"start": start, "end": end,
                                     "speaker": spk_m.group(1)})
        i += 1
    return segments


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


def extract_embeddings(
    audio_wav,
    segments: list[dict],
    *,
    hf_token: str,
    min_duration: float = 2.0,
    sample_rate: int = 16000,
) -> dict[str, list]:
    """
    Extract one embedding per segment, grouped by speaker.
    Uses the embedding model bundled inside pyannote/speaker-diarization-3.1
    (avoids needing separate access to pyannote/embedding).
    Skips segments shorter than min_duration seconds.
    """
    import numpy as np
    import torch
    from pyannote.audio import Pipeline

    print("Loading pyannote/speaker-diarization-3.1 (for its embedding model)...")
    t0 = time.time()
    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=hf_token)
    pipeline.to(torch.device("cuda"))
    # _embedding is a PyannoteAudioPretrainedSpeakerEmbedding — callable directly:
    #   emb_model(tensor(batch, 1, samples)) → ndarray(batch, dim)
    emb_model = pipeline._embedding
    print(f"  loaded in {time.time()-t0:.1f}s  "
          f"(embedding dim={emb_model.dimension}, sr={emb_model.sample_rate})")

    audio_dur = len(audio_wav) / sample_rate
    min_samples = max(emb_model.min_num_samples,
                      int(min_duration * sample_rate))

    by_speaker: dict[str, list] = {}
    skipped = 0
    total = 0

    speakers = sorted({s["speaker"] for s in segments})
    print(f"Extracting embeddings for {len(speakers)} speakers "
          f"from {len(segments)} cues...")

    for seg in segments:
        o_end = min(seg["end"], audio_dur)
        s_idx = int(seg["start"] * sample_rate)
        e_idx = int(o_end * sample_rate)
        if e_idx - s_idx < min_samples:
            skipped += 1
            continue
        try:
            chunk = audio_wav[s_idx:e_idx]
            # emb_model expects (batch=1, channels=1, samples)
            t = torch.from_numpy(chunk).unsqueeze(0).unsqueeze(0)
            emb = emb_model(t)           # → ndarray (1, dim)
            emb = np.array(emb[0])       # → (dim,)
            by_speaker.setdefault(seg["speaker"], []).append(emb)
            total += 1
        except Exception as exc:
            skipped += 1
            print(f"  WARN: skipped {seg['start']:.1f}-{o_end:.1f}: {exc}")

    print(f"  {total} embeddings extracted, {skipped} skipped (< {min_duration}s)")
    for spk, embs in sorted(by_speaker.items()):
        print(f"  {spk}: {len(embs)} embeddings")

    return by_speaker


def build_profiles(by_speaker: dict[str, list]) -> dict[str, "np.ndarray"]:
    """Mean embedding per speaker (L2-normalised)."""
    import numpy as np
    profiles = {}
    for spk, embs in by_speaker.items():
        mean = np.mean(embs, axis=0)
        mean /= np.linalg.norm(mean) + 1e-8
        profiles[spk] = mean
    return profiles


def load_profiles(path: Path) -> dict[str, "np.ndarray"]:
    import numpy as np
    data = np.load(path, allow_pickle=True).item()
    return data  # dict: {name: embedding_array}


def save_profiles(profiles: dict, path: Path) -> None:
    import numpy as np
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, profiles)
    print(f"Saved profiles to {path}")
    for name, emb in profiles.items():
        print(f"  {name}: {emb.shape[0]}-dim embedding")


def cosine_similarity(a, b) -> float:
    import numpy as np
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("audio", type=Path, help="Audio file (mp3/wav)")
    parser.add_argument("vtt", type=Path, help="Labeled WebVTT transcript")
    parser.add_argument("-o", "--output", type=Path,
                        default=Path("transcripts/speaker_profiles.npy"),
                        help="Output .npy profile file")
    parser.add_argument("--merge", action="store_true",
                        help="Merge with existing profile file instead of overwriting")
    parser.add_argument("--min-duration", type=float, default=2.0,
                        help="Minimum cue duration in seconds to use (default: 2.0)")
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

    # Parse VTT
    print(f"Parsing {args.vtt.name}...")
    segments = parse_vtt_segments(args.vtt)
    speakers = sorted({s["speaker"] for s in segments})
    print(f"  {len(segments)} labeled cues, speakers: {', '.join(speakers)}")

    # Load audio
    print(f"Decoding {args.audio.name}...")
    t0 = time.time()
    wav = load_audio(str(args.audio))
    print(f"  {len(wav)/16000/60:.1f} min decoded in {time.time()-t0:.1f}s")

    # Extract embeddings
    by_speaker = extract_embeddings(wav, segments, hf_token=hf_token,
                                    min_duration=args.min_duration)

    # Build mean profiles
    new_profiles = build_profiles(by_speaker)

    # Optionally merge with existing
    if args.merge and args.output.exists():
        print(f"\nMerging with existing profiles in {args.output}...")
        existing = load_profiles(args.output)
        import numpy as np
        for name, emb in new_profiles.items():
            if name in existing:
                # Average the two profiles (equally weighted)
                merged = (existing[name] + emb) / 2
                merged /= np.linalg.norm(merged) + 1e-8
                new_profiles[name] = merged
                print(f"  Merged: {name}")
            else:
                print(f"  Added:  {name}")
        # Keep profiles for speakers not in new data
        for name in existing:
            if name not in new_profiles:
                new_profiles[name] = existing[name]
                print(f"  Kept:   {name}")

    # Save
    print()
    save_profiles(new_profiles, args.output)

    # Sanity check: similarity between known speakers
    if len(new_profiles) >= 2:
        names = list(new_profiles.keys())
        print("\nCross-speaker similarities (should be < 0.7 for distinct speakers):")
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                sim = cosine_similarity(new_profiles[names[i]], new_profiles[names[j]])
                flag = "✓" if sim < 0.7 else "⚠ HIGH"
                print(f"  {names[i]} ↔ {names[j]}: {sim:.3f} {flag}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
