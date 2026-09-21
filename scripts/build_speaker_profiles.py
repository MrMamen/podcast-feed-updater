#!/usr/bin/env python3
"""Build speaker embedding profiles from a labeled VTT + audio file.

Extracts speaker embeddings for each <v Speaker> in the VTT and saves the
mean embedding per speaker to a .npy file. These profiles are used by
transcribe.py / add_speakers.py / diarize_chapters.py to auto-identify
known speakers in new episodes.

The embedding model is taken from the diarization pipeline, so profiles
must be built with the same pipeline they will be matched with (the
matching code refuses to compare profiles of a different dimension).

Usage:
    uv run python scripts/build_speaker_profiles.py audio.mp3 transcript.vtt \\
        -o transcripts/speaker_profiles.npy

    # Merge additional episodes into existing profiles:
    uv run python scripts/build_speaker_profiles.py audio2.mp3 transcript2.vtt \\
        -o transcripts/speaker_profiles.npy --merge
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from asr_common import (
    DEFAULT_DIARIZATION_MODEL,
    MIN_EMBED_SECONDS,
    embed_chunk,
    embedding_model,
    load_audio,
    load_diarization_pipeline,
    load_hf_token,
    load_corrections,
    load_profiles,
    parse_vtt,
    resolve_full_name,
    save_profiles,
    setup_cuda_paths,
)

setup_cuda_paths()


def extract_embeddings(audio_wav, segments: list[dict], emb_model, *,
                       min_duration: float = MIN_EMBED_SECONDS,
                       sample_rate: int = 16000) -> dict[str, list]:
    """One embedding per labeled cue, grouped by speaker.

    Skips cues shorter than min_duration and any NaN embeddings.
    """
    audio_dur = len(audio_wav) / sample_rate
    min_samples = max(emb_model.min_num_samples, int(min_duration * sample_rate))

    by_speaker: dict[str, list] = {}
    skipped = nan_skipped = total = 0
    speakers = sorted({s["speaker"] for s in segments})
    print(f"Extracting embeddings for {len(speakers)} speakers "
          f"from {len(segments)} cues...")

    for seg in segments:
        s_idx = int(seg["start"] * sample_rate)
        e_idx = int(min(seg["end"], audio_dur) * sample_rate)
        if e_idx - s_idx < min_samples:
            skipped += 1
            continue
        emb = embed_chunk(emb_model, audio_wav[s_idx:e_idx])
        if emb is None:
            nan_skipped += 1
            continue
        by_speaker.setdefault(seg["speaker"], []).append(emb)
        total += 1

    print(f"  {total} embeddings extracted, "
          f"{skipped} skipped (< {min_duration}s), "
          f"{nan_skipped} skipped (NaN/failed embedding)")
    for spk, embs in sorted(by_speaker.items()):
        print(f"  {spk}: {len(embs)} embeddings")
    return by_speaker


def build_profiles(by_speaker: dict[str, list]) -> dict:
    """Mean embedding per speaker (L2-normalised)."""
    import numpy as np
    profiles = {}
    for spk, embs in by_speaker.items():
        mean = np.mean(embs, axis=0)
        mean /= np.linalg.norm(mean) + 1e-8
        profiles[spk] = mean
    return profiles


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
    parser.add_argument("--min-duration", type=float, default=MIN_EMBED_SECONDS,
                        help=f"Minimum cue duration in seconds to use (default: {MIN_EMBED_SECONDS})")
    parser.add_argument("--diarization-model", default=DEFAULT_DIARIZATION_MODEL,
                        help="Pipeline whose embedding model to use")
    parser.add_argument("--env", type=Path)
    args = parser.parse_args()

    hf_token = load_hf_token(args.env)
    if not hf_token:
        sys.stderr.write("HF_TOKEN not set\n")
        return 1

    print(f"Parsing {args.vtt.name}...")
    # Tags are short display names ("Jostein"); profiles are keyed by full
    # name, so map back when the output file already knows the person.
    known = list(load_profiles(args.output)) if args.output.exists() else []
    corr = load_corrections()
    segments = [{"start": c["start"], "end": c["end"],
                 "speaker": resolve_full_name(c["speaker"], known, corr)}
                for c in parse_vtt(args.vtt) if c["speaker"]]
    speakers = sorted({s["speaker"] for s in segments})
    print(f"  {len(segments)} labeled cues, speakers: {', '.join(speakers)}")

    print(f"Decoding {args.audio.name}...")
    t0 = time.time()
    wav = load_audio(args.audio)
    print(f"  {len(wav)/16000/60:.1f} min decoded in {time.time()-t0:.1f}s")

    pipeline = load_diarization_pipeline(hf_token, args.diarization_model)
    emb_model = embedding_model(pipeline)
    print(f"  embedding dim={emb_model.dimension}, sr={emb_model.sample_rate}")

    by_speaker = extract_embeddings(wav, segments, emb_model,
                                    min_duration=args.min_duration)
    new_profiles = build_profiles(by_speaker)

    if args.merge and args.output.exists():
        import numpy as np
        print(f"\nMerging with existing profiles in {args.output}...")
        existing = load_profiles(args.output)
        for name, emb in new_profiles.items():
            if name in existing:
                merged = (existing[name] + emb) / 2
                merged /= np.linalg.norm(merged) + 1e-8
                new_profiles[name] = merged
                print(f"  Merged: {name}")
            else:
                print(f"  Added:  {name}")
        for name in existing:
            if name not in new_profiles:
                new_profiles[name] = existing[name]
                print(f"  Kept:   {name}")

    print()
    save_profiles(new_profiles, args.output)
    print(f"Saved {len(new_profiles)} profiles to {args.output}")

    if len(new_profiles) >= 2:
        import numpy as np
        print("\nCross-speaker similarities (should be < 0.7 for distinct speakers):")
        names = list(new_profiles)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                sim = float(np.dot(new_profiles[names[i]], new_profiles[names[j]]))
                flag = "✓" if sim < 0.7 else "⚠ HIGH"
                print(f"  {names[i]} ↔ {names[j]}: {sim:.3f} {flag}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
