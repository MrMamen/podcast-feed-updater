"""Shared helpers for the transcription scripts.

Everything the transcribe / diarize / profile scripts have in common lives
here so that fixes (NaN-safe embeddings, exclusive profile matching, CUDA
library paths) are made once.

Import order matters for CUDA: call ``setup_cuda_paths()`` before anything
imports torch or ctranslate2. The module itself only imports the standard
library at load time; torch/numpy/pyannote are imported lazily inside the
functions that need them.
"""
from __future__ import annotations

import json
import os
import re
import sys
import sysconfig
import time
from collections import defaultdict
from pathlib import Path

SAMPLE_RATE = 16000

# Default diarization pipeline. community-1 (pyannote.audio 4.x) counts and
# assigns speakers better than the 3.1 legacy pipeline and offers a
# non-overlapping "exclusive" output that maps cleanly onto transcript cues.
DEFAULT_DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"
LEGACY_DIARIZATION_MODEL = "pyannote/speaker-diarization-3.1"

# Profile matching threshold. Real matches are typically 0.83-0.94, while
# false positives from vaguely similar voices land at 0.55-0.62.
PROFILE_THRESHOLD = 0.65

# Minimum audio length for a usable speaker embedding. Pyannote's pooling
# layer can return NaN on segments shorter than ~2 s.
MIN_EMBED_SECONDS = 2.0


# --------------------------------------------------------------------------
# Environment
# --------------------------------------------------------------------------
def setup_cuda_paths() -> None:
    """Put the pip-installed NVIDIA libraries on LD_LIBRARY_PATH.

    ctranslate2 (CUDA 12 wheels) and torch (CUDA 13 wheels) dlopen their
    libraries lazily, so os.environ alone is not enough: the process re-execs
    itself once with the paths set so the dynamic linker sees them from the
    start. No-op when the paths are already present or on non-venv installs.
    """
    site = Path(sysconfig.get_paths()["purelib"]) / "nvidia"
    if not site.exists():
        return
    paths = [str(site / sub) for sub in ("cu13/lib", "cublas/lib", "cudnn/lib", "cuda_nvrtc/lib")
             if (site / sub).exists()]
    if not paths:
        return
    existing = os.environ.get("LD_LIBRARY_PATH", "")
    if all(p in existing.split(":") for p in paths):
        return
    env = {k: v for k, v in os.environ.items() if not k.startswith("BASH_FUNC_")}
    env["LD_LIBRARY_PATH"] = ":".join(paths + ([existing] if existing else []))
    os.execve(sys.executable, [sys.executable] + sys.argv, env)


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_hf_token(env_path: Path | None = None) -> str | None:
    """Load .env (project root by default) and return HF_TOKEN if set."""
    env_path = env_path or (project_root() / ".env")
    if env_path.exists():
        from dotenv import load_dotenv
        load_dotenv(env_path)
    return os.environ.get("HF_TOKEN")


# --------------------------------------------------------------------------
# Timestamps
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


# --------------------------------------------------------------------------
# Audio
# --------------------------------------------------------------------------
# Local episode library: one folder per episode named "<number> <title>",
# holding the raw tracks (flac/wav) and the finished mix as an .mp3.
DEFAULT_AUDIO_LIBRARY = Path(os.environ.get("CDSPILL_LIBRARY", "/mnt/t/MrMamen/CD SPILL"))


def find_episode_audio(number: int, library: Path = DEFAULT_AUDIO_LIBRARY) -> Path:
    """Locate the finished mix for an episode number in the local library.

    Folders whose name starts with the number are candidates ("114 pickup"
    style extras are ignored when a main folder exists). Inside, the mix is
    the largest .mp3 that isn't an "_enriched" copy; if the folder has no
    mp3 at all, the largest file with MIX in its name is used instead.
    """
    if not library.exists():
        raise FileNotFoundError(f"Audio library not found: {library} "
                                f"(set CDSPILL_LIBRARY or pass --library)")
    pat = re.compile(rf"^{number}(\s|$)")
    dirs = [d for d in library.iterdir() if d.is_dir() and pat.match(d.name)]
    main = [d for d in dirs if "pickup" not in d.name.lower()]
    dirs = main or dirs
    if not dirs:
        raise FileNotFoundError(f"No folder for episode {number} in {library}")

    def biggest(files):
        return max(files, key=lambda p: p.stat().st_size) if files else None

    for d in dirs:
        mp3s = [p for p in d.glob("*.mp3") if "enriched" not in p.name.lower()]
        pick = biggest(mp3s)
        if pick is None:
            mixes = [p for p in d.iterdir()
                     if p.suffix.lower() in (".flac", ".wav", ".mp3") and "mix" in p.name.lower()]
            pick = biggest(mixes)
        if pick is not None:
            print(f"Episode {number} audio: {pick}")
            return pick

    listing = ", ".join(sorted(p.name for d in dirs for p in d.iterdir()
                               if p.suffix.lower() in (".mp3", ".flac", ".wav", ".m4a")))
    raise FileNotFoundError(f"No mix found in {[str(d) for d in dirs]}. "
                            f"Audio files there: {listing or 'none'}")


def load_audio(path: str | Path, sample_rate: int = SAMPLE_RATE):
    """Decode MP3/WAV/etc to a mono float32 numpy array via PyAV."""
    import av
    import numpy as np

    container = av.open(str(path))
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
# Diarization
# --------------------------------------------------------------------------
def load_diarization_pipeline(hf_token: str | None,
                              model: str = DEFAULT_DIARIZATION_MODEL):
    """Load a pyannote pipeline onto the GPU."""
    import torch
    from pyannote.audio import Pipeline

    if not hf_token:
        raise RuntimeError("HF_TOKEN required for diarization (set in .env)")
    print(f"Loading pyannote pipeline: {model}")
    t0 = time.time()
    pipeline = Pipeline.from_pretrained(model, token=hf_token)
    pipeline.to(torch.device("cuda"))
    print(f"  loaded in {time.time()-t0:.1f}s")
    return pipeline


def run_diarization(pipeline, wav, *, num_speakers: int | None = None,
                    min_speakers: int | None = None, max_speakers: int | None = None,
                    exclusive: bool = True, sample_rate: int = SAMPLE_RATE,
                    verbose: bool = True) -> list[dict]:
    """Run diarization on an in-memory waveform.

    Returns a list of {"start", "end", "speaker"} dicts. With ``exclusive``
    (default) the pipeline's non-overlapping output is used when available,
    so at most one speaker is active at any moment, which is what a
    transcript cue needs. Set exclusive=False for the raw, overlapping
    annotation.
    """
    import torch

    kwargs = {}
    if num_speakers:
        kwargs["num_speakers"] = num_speakers
    else:
        if min_speakers:
            kwargs["min_speakers"] = min_speakers
        if max_speakers:
            kwargs["max_speakers"] = max_speakers

    if verbose:
        hint = ", ".join(f"{k}={v}" for k, v in kwargs.items()) or "no speaker hint"
        print(f"Running diarization ({hint})...")
    t0 = time.time()
    waveform = torch.from_numpy(wav).unsqueeze(0)
    result = pipeline({"waveform": waveform, "sample_rate": sample_rate}, **kwargs)

    ann = None
    if exclusive:
        ann = getattr(result, "exclusive_speaker_diarization", None)
    if ann is None:
        ann = getattr(result, "speaker_diarization", result)
    elapsed = time.time() - t0

    segments = [{"start": turn.start, "end": turn.end, "speaker": spk}
                for turn, _, spk in ann.itertracks(yield_label=True)]

    if verbose:
        totals = speaker_totals(segments)
        dur = len(wav) / sample_rate
        print(f"  {len(totals)} speakers, {len(segments)} turns in {elapsed:.1f}s")
        for spk in sorted(totals, key=lambda x: -totals[x]):
            print(f"    {spk}: {totals[spk]/60:.1f} min ({totals[spk]/dur*100:.0f}%)")
    return segments


def speaker_totals(segments: list[dict]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for s in segments:
        totals[s["speaker"]] += s["end"] - s["start"]
    return dict(totals)


def speaker_for_range(segments: list[dict], start: float, end: float) -> str | None:
    """Speaker with the most overlap in [start, end], or None."""
    overlap: dict[str, float] = defaultdict(float)
    for s in segments:
        if s["end"] < start or s["start"] > end:
            continue
        ovl = min(s["end"], end) - max(s["start"], start)
        if ovl > 0:
            overlap[s["speaker"]] += ovl
    return max(overlap, key=overlap.get) if overlap else None


# --------------------------------------------------------------------------
# Speaker embeddings / profiles
# --------------------------------------------------------------------------
def embedding_model(pipeline):
    """The pretrained speaker-embedding model inside a diarization pipeline."""
    return pipeline._embedding


def embed_chunk(emb_model, chunk):
    """Embedding for one mono float32 chunk, or None if unusable (NaN)."""
    import numpy as np
    import torch

    try:
        t = torch.from_numpy(chunk).unsqueeze(0).unsqueeze(0)
        emb = np.array(emb_model(t)[0])
    except Exception:
        return None
    if np.isnan(emb).any():
        return None
    return emb


def cluster_embeddings(diar_segments: list[dict], wav, pipeline, *,
                       sample_rate: int = SAMPLE_RATE, max_segments: int = 30,
                       min_seconds: float = MIN_EMBED_SECONDS) -> dict:
    """Mean L2-normalised embedding per diarization cluster.

    Uses the longest segments of each cluster; drops segments shorter than
    ``min_seconds`` and any NaN embeddings so short cues ("Mhm", "Ja") don't
    poison the cluster mean.
    """
    import numpy as np

    emb_model = embedding_model(pipeline)
    min_samples = max(emb_model.min_num_samples, int(min_seconds * sample_rate))

    by_speaker: dict[str, list] = defaultdict(list)
    for seg in diar_segments:
        by_speaker[seg["speaker"]].append(seg)

    out: dict[str, np.ndarray] = {}
    for spk, segs in sorted(by_speaker.items()):
        long_segs = sorted(segs, key=lambda s: s["end"] - s["start"], reverse=True)[:max_segments]
        embs = []
        for seg in long_segs:
            s_idx = int(seg["start"] * sample_rate)
            e_idx = int(seg["end"] * sample_rate)
            if e_idx - s_idx < min_samples:
                continue
            emb = embed_chunk(emb_model, wav[s_idx:e_idx])
            if emb is not None:
                embs.append(emb)
        if not embs:
            print(f"  ⚠ {spk}: no usable embeddings (segments too short)")
            continue
        mean = np.mean(embs, axis=0)
        mean /= np.linalg.norm(mean) + 1e-8
        out[spk] = mean
    return out


def load_profiles(path: Path) -> dict:
    import numpy as np
    return np.load(path, allow_pickle=True).item()


def save_profiles(profiles: dict, path: Path) -> None:
    import numpy as np
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, profiles)


def match_profiles(diar_segments: list[dict], wav, pipeline, profiles_path: Path, *,
                   threshold: float = PROFILE_THRESHOLD,
                   sample_rate: int = SAMPLE_RATE) -> dict[str, str]:
    """Map SPEAKER_XX clusters to profile names by cosine similarity.

    Greedy 1:1 assignment, highest similarity first, so a profile is used at
    most once per episode. Returns {speaker_id: name} for confident matches.
    """
    import numpy as np

    profiles = load_profiles(profiles_path)
    dim = next(iter(profiles.values())).shape[0]
    emb_dim = embedding_model(pipeline).dimension
    if dim != emb_dim:
        print(f"  ⚠ profiles are {dim}-dim but pipeline embeddings are {emb_dim}-dim; "
              f"rebuild profiles with this pipeline. Skipping profile matching.")
        return {}

    print(f"Matching clusters against {len(profiles)} profiles...")
    cluster_embs = cluster_embeddings(diar_segments, wav, pipeline, sample_rate=sample_rate)

    pairs = []
    sim_table: dict[str, dict[str, float]] = {}
    for spk, emb in cluster_embs.items():
        sim_table[spk] = {}
        for name, prof_emb in profiles.items():
            sim = float(np.dot(emb, prof_emb))
            if np.isnan(sim):
                continue
            sim_table[spk][name] = sim
            pairs.append((sim, spk, name))

    speaker_map: dict[str, str] = {}
    used: set[str] = set()
    for sim, spk, name in sorted(pairs, reverse=True):
        if spk in speaker_map or name in used:
            continue
        if sim < threshold:
            break
        speaker_map[spk] = name
        used.add(name)

    for spk in sorted(cluster_embs):
        sims = sim_table[spk]
        top = sorted(sims.items(), key=lambda x: -x[1])[:3]
        top_str = "  ".join(f"{n}={v:.3f}" for n, v in top)
        if spk in speaker_map:
            print(f"  {spk} → {speaker_map[spk]} (sim={sims[speaker_map[spk]]:.3f})  [top: {top_str}]")
        else:
            print(f"  {spk} → unknown  [top: {top_str}]")
    return speaker_map


# --------------------------------------------------------------------------
# Corrections (transcripts/corrections.json)
# --------------------------------------------------------------------------
def load_corrections(path: Path | None = None) -> dict:
    path = path or (project_root() / "transcripts" / "corrections.json")
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def apply_corrections(text: str, config: dict) -> str:
    """Apply every fix type from corrections.json to plain cue text.

    Same order as normalize_transcript.py: error_fixes, word_fixes,
    regex_fixes, phrase_fixes, cleanup_fixes, then post_fixes.
    """
    for fix in config.get("error_fixes", []):
        text = text.replace(fix["from"], fix["to"])
    for old, new in config.get("word_fixes", []):
        if old and old != new:
            text = text.replace(old, new)
    for fix in config.get("regex_fixes", []):
        text = re.sub(fix["pattern"], fix["replacement"], text)
    for fix in config.get("phrase_fixes", []):
        src = fix["from"]
        text = text.replace(" ".join(src) if isinstance(src, list) else src, fix["to"])
    for fix in config.get("cleanup_fixes", []):
        text = text.replace(fix["from"], fix["to"])
    for fix in config.get("post_fixes", []):
        text = text.replace(fix["from"], fix["to"])
    return text


# --------------------------------------------------------------------------
# VTT
# --------------------------------------------------------------------------
TS_LINE_RE = re.compile(r"^(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})")
V_TAG_RE = re.compile(r"^<v ([^>]+)>")


def parse_vtt(path: Path) -> list[dict]:
    """Cues as {"ts_line", "start", "end", "speaker", "lines"}.

    ``lines`` is the cue body with any leading <v> tag stripped from the
    first line; ``speaker`` is that tag's name or None.
    """
    text = path.read_text(encoding="utf-8")
    cues = []
    for block in re.split(r"\n\n+", text):
        lines = block.strip().split("\n")
        idx = next((i for i, ln in enumerate(lines) if TS_LINE_RE.match(ln)), None)
        if idx is None:
            continue
        m = TS_LINE_RE.match(lines[idx])
        body = lines[idx + 1:]
        speaker = None
        if body:
            v = V_TAG_RE.match(body[0])
            if v:
                speaker = v.group(1)
                body[0] = V_TAG_RE.sub("", body[0], count=1)
        cues.append({"ts_line": lines[idx], "start": t2s(m.group(1)),
                     "end": t2s(m.group(2)), "speaker": speaker, "lines": body})
    return cues


def render_vtt(cues: list[dict]) -> str:
    out = ["WEBVTT", ""]
    for c in cues:
        lines = list(c["lines"]) or [""]
        if c.get("speaker"):
            lines[0] = f"<v {c['speaker']}>{lines[0]}"
        out.append(c["ts_line"])
        out.extend(lines)
        out.append("")
    return "\n".join(out)
