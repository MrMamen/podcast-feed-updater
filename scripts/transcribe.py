#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "faster-whisper>=1.2",
#     "pyannote.audio>=4.0",
#     "python-dotenv>=1.0",
#     "av>=13",
#     "torch",
#     "numpy",
# ]
# ///
"""Transcribe a podcast MP3 with NB-Whisper + optional pyannote diarization.

Output: WebVTT with sentence cues, optional <v Speaker> tags.

Requires:
  - NVIDIA GPU with CUDA drivers
  - HF_TOKEN in .env (only for diarization; accept pyannote licenses)
  - nvidia-cu13 pip wheels (bundled via this project's venv)

Usage:
    scripts/transcribe.py <audio.mp3> -o output.vtt
    scripts/transcribe.py <audio.mp3> -o output.vtt --no-diarization
    scripts/transcribe.py <audio.mp3> -o output.vtt \\
        --initial-prompt "Names and terms to bias ASR toward: ..."
    scripts/transcribe.py <audio.mp3> -o output.vtt \\
        --speakers 3 --speaker-map "SPEAKER_01=Sigve,SPEAKER_00=Mr. Mamen"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path


# --------------------------------------------------------------------------
# CUDA library path setup (before importing torch)
# --------------------------------------------------------------------------
def _setup_cuda_paths() -> None:
    """Ensure bundled CUDA libs are on LD_LIBRARY_PATH.

    Sets LD_LIBRARY_PATH and re-execs the process if the paths are missing,
    so the dynamic linker sees them from process startup (os.environ alone is
    not sufficient for libraries loaded lazily by ctranslate2).
    """
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
        return  # Already configured, no re-exec needed
    # Re-exec with correct LD_LIBRARY_PATH so dynamic linker sees it at startup
    import sys
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


def t2s(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


# --------------------------------------------------------------------------
# Audio loading
# --------------------------------------------------------------------------
def load_audio(path: str, sample_rate: int = 16000):
    """Decode MP3/WAV/etc to mono float32 numpy array via PyAV."""
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
        wav = wav[0]  # mono: take first channel
    return wav


# --------------------------------------------------------------------------
# Transcription (NB-Whisper)
# --------------------------------------------------------------------------
def transcribe(audio_wav, *, model_name: str, language: str = "no",
               initial_prompt: str | None = None, beam_size: int = 5):
    from faster_whisper import WhisperModel

    print(f"Loading Whisper: {model_name}")
    t0 = time.time()
    model = WhisperModel(model_name, device="cuda", compute_type="float16")
    print(f"  loaded in {time.time()-t0:.1f}s")

    print(f"Transcribing ({len(audio_wav)/16000/60:.1f} min audio)...")
    t0 = time.time()
    kwargs = dict(language=language, beam_size=beam_size, vad_filter=True)
    if initial_prompt:
        kwargs["initial_prompt"] = initial_prompt
    segments, info = model.transcribe(audio_wav, **kwargs)
    segs = list(segments)
    elapsed = time.time() - t0
    print(f"  {len(segs)} segments in {elapsed:.1f}s "
          f"({info.duration/elapsed:.1f}x realtime)")
    return segs, info.duration


# --------------------------------------------------------------------------
# Diarization (pyannote)
# --------------------------------------------------------------------------
def diarize(audio_wav, *, num_speakers: int | None = None,
            hf_token: str | None = None):
    import torch
    from pyannote.audio import Pipeline

    if not hf_token:
        raise RuntimeError("HF_TOKEN required for diarization (set in .env)")

    print("Loading pyannote pipeline...")
    t0 = time.time()
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1", token=hf_token
    )
    pipeline.to(torch.device("cuda"))
    print(f"  loaded in {time.time()-t0:.1f}s")

    print("Running diarization...")
    t0 = time.time()
    waveform = torch.from_numpy(audio_wav).unsqueeze(0)
    kwargs = {}
    if num_speakers:
        kwargs["num_speakers"] = num_speakers
    result = pipeline({"waveform": waveform, "sample_rate": 16000}, **kwargs)
    ann = result.speaker_diarization if hasattr(result, "speaker_diarization") else result
    elapsed = time.time() - t0

    segments = []
    for turn, _, speaker in ann.itertracks(yield_label=True):
        segments.append({"start": turn.start, "end": turn.end, "speaker": speaker})
    speakers = {s["speaker"] for s in segments}
    print(f"  {len(speakers)} speakers, {len(segments)} turns in {elapsed:.1f}s")

    # Stats
    from collections import defaultdict
    totals: dict[str, float] = defaultdict(float)
    for s in segments:
        totals[s["speaker"]] += s["end"] - s["start"]
    for spk in sorted(totals, key=lambda x: -totals[x]):
        print(f"    {spk}: {totals[spk]/60:.1f} min")

    return segments, pipeline


def match_profiles(diar_segments: list, audio_wav, pipeline,
                   profiles_path: Path, *, threshold: float = 0.5,
                   sample_rate: int = 16000) -> dict[str, str]:
    """Match SPEAKER_XX clusters against saved voice profiles.
    Returns {speaker_id: name} for confident matches."""
    import numpy as np
    import torch
    from collections import defaultdict

    profiles = np.load(profiles_path, allow_pickle=True).item()
    emb_model = pipeline._embedding

    by_speaker: dict[str, list] = defaultdict(list)
    for seg in diar_segments:
        by_speaker[seg["speaker"]].append(seg)

    speaker_map: dict[str, str] = {}
    print(f"Matching {len(by_speaker)} clusters against "
          f"{len(profiles)} profiles...")

    for spk, segs in sorted(by_speaker.items()):
        long_segs = sorted(segs, key=lambda s: s["end"] - s["start"],
                           reverse=True)[:30]
        embs = []
        for seg in long_segs:
            s_idx = int(seg["start"] * sample_rate)
            e_idx = int(seg["end"] * sample_rate)
            if e_idx - s_idx < emb_model.min_num_samples:
                continue
            try:
                chunk = audio_wav[s_idx:e_idx]
                t = torch.from_numpy(chunk).unsqueeze(0).unsqueeze(0)
                emb = np.array(emb_model(t)[0])
                embs.append(emb)
            except Exception:
                continue
        if not embs:
            continue

        cluster_emb = np.mean(embs, axis=0)
        cluster_emb /= np.linalg.norm(cluster_emb) + 1e-8

        sims = {}
        for name, prof_emb in profiles.items():
            sims[name] = float(np.dot(cluster_emb, prof_emb))

        best_name = max(sims, key=sims.get)
        best_sim = sims[best_name]
        sim_str = "  ".join(f"{n}={v:.3f}" for n, v in sorted(sims.items()))

        if best_sim >= threshold:
            speaker_map[spk] = best_name
            print(f"  {spk} → {best_name} (sim={best_sim:.3f})  [{sim_str}]")
        else:
            print(f"  {spk} → unknown (best {best_name}={best_sim:.3f})  [{sim_str}]")

    return speaker_map


def speaker_for_range(segments, start: float, end: float) -> str | None:
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


# --------------------------------------------------------------------------
# Episode metadata lookup (RSS feed)
# --------------------------------------------------------------------------
def fetch_rss(project_root: Path, refresh: bool = False) -> str:
    """Return CDspill feed XML.

    Priority:
      1. output/cdspill-enriched.xml (local enriched, has podcast:person guest tags)
      2. .cache/cdspill_feed.xml   (cached Podbean original, refreshed every 24 h)
      3. Live fetch from Podbean   (when cache is missing or --refresh-rss)
    """
    import urllib.request

    # 1. Local enriched feed — richer metadata, no network needed
    enriched = project_root / "output" / "cdspill-enriched.xml"
    if enriched.exists():
        print(f"Using local enriched feed: {enriched.relative_to(project_root)}")
        return enriched.read_text(encoding="utf-8")

    # 2/3. Fall back to Podbean with local cache
    cache_dir = project_root / ".cache"
    cache_dir.mkdir(exist_ok=True)
    cached = cache_dir / "cdspill_feed.xml"

    if not refresh and cached.exists():
        age_hours = (time.time() - cached.stat().st_mtime) / 3600
        if age_hours < 24:
            print("Using cached Podbean feed (run enrich_cdspill.py for guest metadata)")
            return cached.read_text(encoding="utf-8")

    print("Fetching CDspill RSS feed from Podbean...")
    url = "https://feed.podbean.com/cdspill/feed.xml"
    req = urllib.request.Request(url, headers={"User-Agent": "cdspill-transcribe"})
    with urllib.request.urlopen(req, timeout=30) as r:
        content = r.read().decode("utf-8")
    cached.write_text(content, encoding="utf-8")
    return content


def find_episode(feed_xml: str, *, number: int | None = None,
                 guid: str | None = None, title_contains: str | None = None) -> dict | None:
    """Return episode metadata dict {title, description, guid, chapters_url, people}.

    Episode number is read from <itunes:episode>; falls back to scanning title
    for "#NNN" if absent.
    """
    items = re.findall(r"<item>(.+?)</item>", feed_xml, re.DOTALL)
    for item in items:
        title_m = re.search(r"<title[^>]*>(.+?)</title>", item, re.DOTALL)
        if not title_m:
            continue
        title = re.sub(r"<!\[CDATA\[|\]\]>", "", title_m.group(1)).strip()
        guid_m = re.search(r"<guid[^>]*>(.+?)</guid>", item)
        ep_guid = guid_m.group(1) if guid_m else None

        # Authoritative episode number from <itunes:episode>; fallback to "(#NNN)" in title
        num_m = re.search(r"<itunes:episode>\s*(\d+)\s*</itunes:episode>", item)
        if num_m:
            ep_num = int(num_m.group(1))
        else:
            hash_m = re.search(r"#(\d+)\)?\s*$", title)
            ep_num = int(hash_m.group(1)) if hash_m else None

        match = False
        if number is not None and ep_num == number:
            match = True
        if guid and ep_guid and guid in ep_guid:
            match = True
        if title_contains and title_contains.lower() in title.lower():
            match = True
        if not match:
            continue

        desc_m = re.search(r"<description[^>]*>(.+?)</description>", item, re.DOTALL)
        desc = ""
        if desc_m:
            desc = re.sub(r"<!\[CDATA\[|\]\]>", "", desc_m.group(1))
            desc = re.sub(r"<[^>]+>", " ", desc)
            desc = re.sub(r"\s+", " ", desc).strip()

        chapters_m = re.search(r'<podcast:chapters[^>]*url="([^"]+)"', item)
        chapters_url = chapters_m.group(1) if chapters_m else None

        people = re.findall(r">([^<]+)</podcast:person>", item)

        return {
            "number": ep_num,
            "title": title,
            "guid": ep_guid,
            "description": desc,
            "chapters_url": chapters_url,
            "people": people,
        }
    return None


def build_initial_prompt(meta: dict, project_root: Path,
                         extra_terms: list[str] | None = None) -> str:
    """Build NB-Whisper initial_prompt string from episode metadata."""
    parts = []

    # Standard podcast vocabulary
    parts.append("cd SPILL podcast. Verter: Mr. Mamen og Sigve. Aleksikon.")

    # Guests from <podcast:person> tags
    if meta.get("people"):
        parts.append("Gjester: " + ", ".join(meta["people"]) + ".")

    # Title keywords (game name is usually in title)
    parts.append(f"Episode: {meta['title']}.")

    # Chapter titles often contain specific game/person names
    if meta.get("chapters_url"):
        chapters_file = meta["chapters_url"].split("/")[-1]
        local_path = project_root / "docs" / "chapters" / chapters_file
        if not local_path.exists():
            local_path = project_root / "chapters" / chapters_file
        if local_path.exists():
            try:
                data = json.loads(local_path.read_text(encoding="utf-8"))
                titles = [c.get("title", "") for c in data.get("chapters", [])]
                # Use full chapter titles as-is (skip generic/short entries)
                _skip = {"Intro", "Outro", "Velkommen", "Takk", "Tilbake"}
                seen = set()
                names = []
                for t in titles:
                    t = t.strip()
                    if not t or t in _skip or len(t) < 4:
                        continue
                    if t not in seen:
                        seen.add(t)
                        names.append(t)
                if names:
                    # Fill as many as fit within remaining prompt budget
                    section = "Nevnte: "
                    budget = 900 - sum(len(p) + 1 for p in parts) - len(section) - 1
                    chosen, used = [], 0
                    for n in names:
                        cost = len(n) + 2  # ", "
                        if used + cost > budget:
                            break
                        chosen.append(n)
                        used += cost
                    if chosen:
                        parts.append(section + ", ".join(chosen) + ".")
            except Exception:
                pass

    if extra_terms:
        parts.append(" ".join(extra_terms))

    prompt = " ".join(parts)
    # Keep under ~240 tokens (~900 chars to be safe)
    return prompt[:900]


# --------------------------------------------------------------------------
# Correction pass (re-uses corrections.json schema)
# --------------------------------------------------------------------------
def apply_word_fixes(text: str, config: dict) -> str:
    for old, new in config.get("word_fixes", []):
        if old and old != new:
            text = text.replace(old, new)
    for fix in config.get("regex_fixes", []):
        text = re.sub(fix["pattern"], fix["replacement"], text)
    for fix in config.get("post_fixes", []):
        text = text.replace(fix["from"], fix["to"])
    for fix in config.get("error_fixes", []):
        text = text.replace(fix["from"], fix["to"])
    return text


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("audio", type=Path, help="Input audio file")
    parser.add_argument("-o", "--output", type=Path, required=True,
                        help="Output VTT path")
    parser.add_argument("--no-diarization", action="store_true",
                        help="Skip pyannote diarization (faster, no <v> tags)")
    parser.add_argument("--speakers", type=int,
                        help="Number of speakers hint for diarization")
    parser.add_argument("--speaker-map", type=str,
                        help='Comma-separated mapping, e.g. "SPEAKER_00=Sigve,SPEAKER_01=Mamen"')
    parser.add_argument("--model", default="TheStigh/nb-whisper-large-ct2",
                        help="Whisper model name (HF repo or local CT2 dir)")
    parser.add_argument("--language", default="no")
    parser.add_argument("--initial-prompt", type=str,
                        help="Bias ASR with names/terms (up to ~240 tokens). "
                             "Auto-built from --episode-* flags if not given.")
    parser.add_argument("--episode-number", type=int,
                        help="CDspill episode number. Auto-fetches RSS metadata "
                             "for initial_prompt and logs speaker candidates.")
    parser.add_argument("--episode-guid", type=str,
                        help="Alternative: match episode by GUID substring")
    parser.add_argument("--episode-title", type=str,
                        help="Alternative: match episode by title fragment")
    parser.add_argument("--refresh-rss", action="store_true",
                        help="Re-download RSS cache instead of using cached copy")
    parser.add_argument("--profiles", type=Path,
                        help="Speaker profiles .npy (built with build_speaker_profiles.py). "
                             "Auto-identifies known speakers after diarization.")
    parser.add_argument("--corrections", type=Path,
                        help="JSON with word/regex/post fixes to apply")
    parser.add_argument("--env", type=Path,
                        help="Path to .env file (default: project root)")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent

    # Load .env for HF_TOKEN
    env_path = args.env or (project_root / ".env")
    if env_path.exists():
        from dotenv import load_dotenv
        load_dotenv(env_path)
    hf_token = os.environ.get("HF_TOKEN")

    if not args.audio.exists():
        sys.stderr.write(f"Audio not found: {args.audio}\n")
        return 1

    # Parse speaker map
    speaker_map: dict[str, str] = {}
    if args.speaker_map:
        for pair in args.speaker_map.split(","):
            k, _, v = pair.partition("=")
            speaker_map[k.strip()] = v.strip()

    # Load corrections (default: transcripts/corrections.json if present)
    corrections: dict = {}
    corr_path = args.corrections or (project_root / "transcripts" / "corrections.json")
    if corr_path.exists():
        corrections = json.loads(corr_path.read_text(encoding="utf-8"))

    # Episode metadata lookup (if requested)
    initial_prompt = args.initial_prompt
    meta = None
    if args.episode_number or args.episode_guid or args.episode_title:
        feed = fetch_rss(project_root, refresh=args.refresh_rss)
        meta = find_episode(feed,
                            number=args.episode_number,
                            guid=args.episode_guid,
                            title_contains=args.episode_title)
        if not meta:
            sys.stderr.write("Episode not found in RSS.\n")
            return 1
        print(f"\nEpisode #{meta['number']}: {meta['title']}")
        if meta["people"]:
            print(f"  Gjester: {', '.join(meta['people'])}")
        if not initial_prompt:
            initial_prompt = build_initial_prompt(meta, project_root)
            print(f"  Auto-prompt: {initial_prompt[:120]}...")

    # Pipeline ---------------------------------------------------------------
    total_t = time.time()

    print(f"Decoding {args.audio.name}...")
    t0 = time.time()
    wav = load_audio(str(args.audio))
    print(f"  {len(wav)/16000/60:.1f} min decoded in {time.time()-t0:.1f}s")

    segs, duration = transcribe(
        wav, model_name=args.model, language=args.language,
        initial_prompt=initial_prompt,
    )

    diar_segments = None
    pipeline = None
    if not args.no_diarization:
        if not hf_token:
            sys.stderr.write(
                "WARN: HF_TOKEN not set, skipping diarization. "
                "Use --no-diarization to silence this warning.\n"
            )
        else:
            diar_segments, pipeline = diarize(
                wav, num_speakers=args.speakers, hf_token=hf_token
            )

    # Auto-identify known speakers from profiles
    if diar_segments and args.profiles and not speaker_map:
        profile_map = match_profiles(
            diar_segments, wav, pipeline, args.profiles,
        )
        # Merge: profile matches for known hosts, guest names for the rest
        guest_names = [p for p in (meta.get("people", []) if meta else [])
                       if p not in profile_map.values()]
        unmatched = sorted(set(s["speaker"] for s in diar_segments) - set(profile_map))
        speaker_map.update(profile_map)
        # Assign guest names to unmatched speakers by talk-time (most → first guest)
        if guest_names and unmatched:
            from collections import defaultdict as _dd
            totals: dict[str, float] = _dd(float)
            for s in diar_segments:
                if s["speaker"] in unmatched:
                    totals[s["speaker"]] += s["end"] - s["start"]
            for spk in sorted(totals, key=lambda x: -totals[x]):
                if guest_names:
                    speaker_map[spk] = guest_names.pop(0)
                    print(f"  {spk} → {speaker_map[spk]} (guest from metadata)")

    # Merge + render VTT -----------------------------------------------------
    print(f"\nWriting {args.output}...")
    lines = ["WEBVTT", ""]
    for seg in segs:
        text = seg.text.strip()
        text = apply_word_fixes(text, corrections)
        speaker = None
        if diar_segments:
            spk = speaker_for_range(diar_segments, seg.start, seg.end)
            speaker = speaker_map.get(spk, spk) if spk else None

        lines.append(f"{format_ts(seg.start)} --> {format_ts(seg.end)}")
        lines.append(f"<v {speaker}>{text}" if speaker else text)
        lines.append("")

    args.output.write_text("\n".join(lines), encoding="utf-8")

    total_elapsed = time.time() - total_t
    print(f"\n✓ Done in {total_elapsed:.1f}s "
          f"({duration/total_elapsed:.1f}x realtime)")
    print(f"  {args.output}")

    # Speaker preview to help user map names
    if diar_segments and not args.speaker_map:
        print("\n--- Speaker preview (first 3 utterances each) ---")
        seen_count: dict[str, int] = {}
        for seg in segs:
            if seen_count.get("all", 0) >= 300:  # stop scanning after 300 cues
                break
            seen_count["all"] = seen_count.get("all", 0) + 1
            spk = speaker_for_range(diar_segments, seg.start, seg.end)
            if not spk:
                continue
            if seen_count.get(spk, 0) >= 3:
                continue
            seen_count[spk] = seen_count.get(spk, 0) + 1
            preview = seg.text.strip()[:90]
            print(f"  {spk} [{format_ts(seg.start)}]: {preview}")

        print("\nTo apply names, re-run with:")
        print('  --speaker-map "SPEAKER_00=Sigve,SPEAKER_01=Mr. Mamen,..."')
        print("Or edit the VTT file directly.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
