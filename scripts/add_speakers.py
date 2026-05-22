"""Re-tag speakers in an existing VTT without re-transcribing.

Useful when:
  - profile set has been updated and you want to re-match an old transcript
  - mix VTT has wrong speaker tags but the text is correct
  - you want to swap profile matching strategy without losing manual edits

Keeps all existing text (including hand-corrections) and only updates the
``<v Speaker>`` tag on each cue based on pyannote diarisation of the audio.

Usage:
    uv run python scripts/add_speakers.py <audio> <vtt> <num_speakers>

The VTT file is overwritten in place. Make a backup if you have unsaved edits.
"""
import os
import re
import sys
import time

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
nvdir = f"{PROJ}/.venv/lib/python3.12/site-packages/nvidia"
paths = [
    f"{nvdir}/cu13/lib",
    f"{nvdir}/cublas/lib",
    f"{nvdir}/cudnn/lib",
    f"{nvdir}/cuda_nvrtc/lib",
]
existing = os.environ.get("LD_LIBRARY_PATH", "")
need = [p for p in paths if p not in existing.split(":")]
if need:
    env = {k: v for k, v in os.environ.items() if not k.startswith("BASH_FUNC_")}
    env["LD_LIBRARY_PATH"] = ":".join(paths + ([existing] if existing else []))
    os.execve(sys.executable, [sys.executable] + sys.argv, env)

if len(sys.argv) < 4:
    print("Usage: add_speakers.py <audio> <vtt> <num_speakers>")
    sys.exit(1)

AUDIO = sys.argv[1]
VTT = sys.argv[2]
NUM_SPEAKERS = int(sys.argv[3])
PROFILES = f"{PROJ}/transcripts/speaker_profiles.npy"
PROFILE_THRESHOLD = 0.65

from collections import defaultdict
from dotenv import load_dotenv
import numpy as np
import torch
import av
from pyannote.audio import Pipeline

load_dotenv(f"{PROJ}/.env")
HF_TOKEN = os.environ.get("HF_TOKEN")

TS_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3}) --> (\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*$")


def parse_ts(parts):
    h, m, s, ms = (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
    return h * 3600 + m * 60 + s + ms / 1000


def load_audio():
    print(f"\nDecoding {AUDIO}...")
    container = av.open(AUDIO)
    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
    chunks = []
    for frame in container.decode(audio=0):
        for r in resampler.resample(frame):
            chunks.append(r.to_ndarray())
    container.close()
    wav = np.concatenate(chunks, axis=-1).astype(np.float32) / 32768.0
    if wav.ndim == 2:
        wav = wav[0]
    print(f"  {len(wav)/16000/60:.1f} min audio")
    return wav


def diarize(wav):
    print("\nLoading pyannote/speaker-diarization-3.1...")
    t0 = time.time()
    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=HF_TOKEN)
    pipeline.to(torch.device("cuda"))
    print(f"  loaded in {time.time()-t0:.1f}s")

    print(f"\nDiarising (num_speakers={NUM_SPEAKERS})...")
    t0 = time.time()
    waveform = torch.from_numpy(wav).unsqueeze(0)
    result = pipeline(
        {"waveform": waveform, "sample_rate": 16000},
        num_speakers=NUM_SPEAKERS,
    )
    ann = result.speaker_diarization if hasattr(result, "speaker_diarization") else result
    segments = [
        {"start": turn.start, "end": turn.end, "speaker": speaker}
        for turn, _, speaker in ann.itertracks(yield_label=True)
    ]
    print(f"  {len(segments)} segments in {time.time()-t0:.1f}s")
    totals = defaultdict(float)
    for s in segments:
        totals[s["speaker"]] += s["end"] - s["start"]
    for spk in sorted(totals, key=lambda x: -totals[x]):
        print(f"    {spk}: {totals[spk]/60:.1f} min")
    return segments, pipeline


def match_profiles(diar_segments, wav, pipeline, threshold=PROFILE_THRESHOLD):
    profiles = np.load(PROFILES, allow_pickle=True).item()
    emb = pipeline._embedding
    by_speaker = defaultdict(list)
    for s in diar_segments:
        by_speaker[s["speaker"]].append(s)

    print(f"\nMatching {len(by_speaker)} clusters against {len(profiles)} profiles...")

    # Min 2s + NaN filter (pyannote pooling std() can return NaN on short
    # segments due to degree-of-freedom; polluted embeddings poison the
    # cluster mean and break greedy 1:1 assignment).
    min_samples = max(emb.min_num_samples, int(2.0 * 16000))

    cluster_embs = {}
    for spk, segs in sorted(by_speaker.items()):
        long_segs = sorted(segs, key=lambda s: s["end"] - s["start"], reverse=True)[:30]
        embs = []
        for seg in long_segs:
            si = int(seg["start"] * 16000)
            ei = int(seg["end"] * 16000)
            if ei - si < min_samples:
                continue
            try:
                t = torch.from_numpy(wav[si:ei]).unsqueeze(0).unsqueeze(0)
                e = np.array(emb(t)[0])
                if np.isnan(e).any():
                    continue
                embs.append(e)
            except Exception:
                continue
        if not embs:
            print(f"  ! {spk}: no valid embeddings")
            continue
        ce = np.mean(embs, axis=0)
        ce /= np.linalg.norm(ce) + 1e-8
        cluster_embs[spk] = ce

    pairs = []
    sim_table = {}
    for spk, ce in cluster_embs.items():
        sim_table[spk] = {}
        for name, pe in profiles.items():
            sim = float(np.dot(ce, pe))
            if np.isnan(sim):
                continue
            sim_table[spk][name] = sim
            pairs.append((sim, spk, name))

    speaker_map = {}
    used = set()
    for sim, spk, name in sorted(pairs, reverse=True):
        if spk in speaker_map or name in used:
            continue
        if sim < threshold:
            break
        speaker_map[spk] = name
        used.add(name)

    for spk in sorted(cluster_embs):
        sims = sim_table[spk]
        top3 = sorted(sims.items(), key=lambda x: -x[1])[:3]
        sim_str = "  ".join(f"{n}={v:.3f}" for n, v in top3)
        if spk in speaker_map:
            print(f"  {spk} -> {speaker_map[spk]} (sim={sims[speaker_map[spk]]:.3f})  [top3: {sim_str}]")
        else:
            print(f"  {spk} -> unknown  [top3: {sim_str}]")
    return speaker_map


def speaker_for_range(diar_segs, start, end):
    overlap = defaultdict(float)
    for s in diar_segs:
        if s["end"] < start or s["start"] > end:
            continue
        ovl = min(s["end"], end) - max(s["start"], start)
        if ovl > 0:
            overlap[s["speaker"]] += ovl
    return max(overlap, key=overlap.get) if overlap else None


def parse_vtt(path):
    text = open(path, encoding="utf-8").read()
    blocks = re.split(r"\n\n+", text)
    cues = []
    for block in blocks:
        lines = block.strip().split("\n")
        if not lines or lines[0].strip() == "WEBVTT":
            continue
        ts_idx = next((i for i, ln in enumerate(lines) if TS_RE.match(ln)), None)
        if ts_idx is None:
            continue
        m = TS_RE.match(lines[ts_idx])
        start = parse_ts((m.group(1), m.group(2), m.group(3), m.group(4)))
        end = parse_ts((m.group(5), m.group(6), m.group(7), m.group(8)))
        content = lines[ts_idx + 1:]
        cues.append((lines[ts_idx], content, start, end))
    return cues


def render_vtt(cues, diar_segs, speaker_map):
    out = ["WEBVTT", ""]
    tagged_count = defaultdict(int)
    untagged = 0
    V_RE = re.compile(r"^<v ([^>]+)>")

    for ts_line, content_lines, start, end in cues:
        spk = speaker_for_range(diar_segs, start, end)
        speaker = speaker_map.get(spk, spk) if spk else None

        new_content = list(content_lines)
        if new_content and V_RE.match(new_content[0]):
            new_content[0] = V_RE.sub("", new_content[0], count=1)

        if speaker:
            new_content[0] = f"<v {speaker}>{new_content[0]}"
            tagged_count[speaker] += 1
        else:
            untagged += 1

        out.append(ts_line)
        out.extend(new_content)
        out.append("")

    print(f"\nTagged cues:")
    for spk in sorted(tagged_count, key=lambda s: -tagged_count[s]):
        print(f"  {spk}: {tagged_count[spk]}")
    if untagged:
        print(f"  (no tag: {untagged})")
    return "\n".join(out)


def main():
    cues = parse_vtt(VTT)
    print(f"VTT has {len(cues)} cues")

    wav = load_audio()
    diar_segs, pipeline = diarize(wav)
    speaker_map = match_profiles(diar_segs, wav, pipeline)

    rendered = render_vtt(cues, diar_segs, speaker_map)

    print(f"\nWriting {VTT}")
    open(VTT, "w", encoding="utf-8").write(rendered)
    print("Done")


if __name__ == "__main__":
    main()
