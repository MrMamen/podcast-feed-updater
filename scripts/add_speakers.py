#!/usr/bin/env python3
"""Re-tag speakers in an existing VTT without re-transcribing.

Useful when:
  - profile set has been updated and you want to re-match an old transcript
  - mix VTT has wrong speaker tags but the text is correct
  - you want to swap profile matching strategy without losing manual edits

Keeps all existing text (including hand-corrections) and only updates the
``<v Speaker>`` tag on each cue based on pyannote diarization of the audio.

Usage:
    uv run python scripts/add_speakers.py <audio> <vtt> --speakers 3
    uv run python scripts/add_speakers.py <audio> <vtt> --min-speakers 2 --max-speakers 4

The VTT file is overwritten in place unless -o is given; --backup keeps a
copy of the original next to it.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from asr_common import (
    DEFAULT_DIARIZATION_MODEL,
    PROFILE_THRESHOLD,
    display_name,
    load_audio,
    load_corrections,
    load_diarization_pipeline,
    load_hf_token,
    match_profiles,
    parse_vtt,
    project_root,
    render_vtt,
    run_diarization,
    setup_cuda_paths,
    speaker_for_range,
)

setup_cuda_paths()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("audio", type=Path)
    parser.add_argument("vtt", type=Path)
    parser.add_argument("-o", "--output", type=Path,
                        help="Write here instead of overwriting the input VTT")
    parser.add_argument("--speakers", type=int, help="Exact number of speakers")
    parser.add_argument("--min-speakers", type=int)
    parser.add_argument("--max-speakers", type=int)
    parser.add_argument("--diarization-model", default=DEFAULT_DIARIZATION_MODEL)
    parser.add_argument("--no-exclusive", action="store_true",
                        help="Use raw overlapping diarization output")
    parser.add_argument("--profiles", type=Path,
                        default=project_root() / "transcripts" / "speaker_profiles.npy")
    parser.add_argument("--profile-threshold", type=float, default=PROFILE_THRESHOLD)
    parser.add_argument("--backup", action="store_true",
                        help="Save <vtt>.bak before overwriting")
    parser.add_argument("--env", type=Path)
    args = parser.parse_args()

    hf_token = load_hf_token(args.env)
    if not hf_token:
        sys.stderr.write("HF_TOKEN not set in .env\n")
        return 1
    if not args.vtt.exists():
        sys.stderr.write(f"VTT not found: {args.vtt}\n")
        return 1

    cues = parse_vtt(args.vtt)
    print(f"VTT has {len(cues)} cues")

    print(f"Decoding {args.audio.name}...")
    wav = load_audio(args.audio)
    print(f"  {len(wav)/16000/60:.1f} min audio")

    pipeline = load_diarization_pipeline(hf_token, args.diarization_model)
    diar_segs = run_diarization(pipeline, wav, num_speakers=args.speakers,
                                min_speakers=args.min_speakers,
                                max_speakers=args.max_speakers,
                                exclusive=not args.no_exclusive)

    speaker_map = {}
    if args.profiles.exists():
        speaker_map = match_profiles(diar_segs, wav, pipeline, args.profiles,
                                     threshold=args.profile_threshold)
    else:
        print(f"(no profiles at {args.profiles}; keeping SPEAKER_XX labels)")

    corrections = load_corrections()
    tagged: Counter = Counter()
    untagged = 0
    for c in cues:
        spk = speaker_for_range(diar_segs, c["start"], c["end"])
        c["speaker"] = display_name(speaker_map.get(spk, spk), corrections) if spk else None
        if c["speaker"]:
            tagged[c["speaker"]] += 1
        else:
            untagged += 1

    print("\nTagged cues:")
    for spk, n in tagged.most_common():
        print(f"  {spk}: {n}")
    if untagged:
        print(f"  (no tag: {untagged})")

    output = args.output or args.vtt
    if args.backup and output == args.vtt:
        bak = args.vtt.with_suffix(args.vtt.suffix + ".bak")
        bak.write_text(args.vtt.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Backup: {bak}")
    output.write_text(render_vtt(cues), encoding="utf-8")
    print(f"\nWrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
