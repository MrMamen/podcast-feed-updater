#!/usr/bin/env python3
"""Transcribe each speaker's microphone as it plays in the edited episode.

Every self-edited episode folder has the Reaper project (`.rpp`) and one
recording per microphone. The project lists every item on every track with
its position in the mix, its length and its offset into the source file. This
script uses that map to build one "stem" per speaker: a track holding only
that microphone's items, each at its mix position, i.e. what Reaper would
render with that track soloed. Each stem is transcribed on its own, so

  * the text comes from a clean single voice (better than the mixed audio),
  * the speaker of every word is certain (no pyannote, no guessing),
  * timestamps are mix time directly, and nothing that was cut is included.

Whisper drops stretches of speech in long files, in both decoding modes, so
each stem is transcribed in three passes: sequential (best text), batched
(fills runs the first pass missed), and every >= 2 s stretch that Silero VAD
calls speech but still has no word, transcribed on its own. The result is
cached in .cache/raw/<stem>.stems.json (redone when the .rpp changes or with
--redo-stems), and written as the raw cache .cache/raw/<stem>.json with a
speaker on every segment, ready for `transcribe.py --render-only`. The mix
transcript from transcribe.py is not needed.

Files on the other tracks (music, effects, game audio) are checked with
Silero VAD; those that contain speech are transcribed from the clean file
with a multilingual model and automatic language detection (NB-Whisper would
translate them) and tagged "Spillklipp". --item sets the tag (a character
name) and optionally the language for a file: "file.wav=Game|en". A produced
clip on a speaker's track (an intro, a sketch) counts as that microphone
unless it is given with --item.

The stem text and a 0.1 s loudness envelope per speaker are kept in the
cache (solo_segments, stem_envelope) for `language_pass.py check`.

Usage:
    uv run python scripts/align_solo.py -o transcripts/TA.vtt --episode-number 120 \\
        --item "Total Annihilation - Intro Cinematic.wav=Forteller|en"
    uv run python scripts/transcribe.py -o transcripts/TA.vtt --render-only

--mix-text is the earlier mode: run `transcribe.py --no-diarization` on the
mix first; this script then transcribes the raw solo files, moves their words
into mix time and uses them only for speaker tags and to fill gaps in the mix
text. It is worse (raw files include speech that was cut, and the mix text
garbles overlaps) and is kept for comparison.

Speaker tracks are recognised by name: the hosts' tracks ("Mamen", "Sigve"),
a track named like a person in the episode's <podcast:person> list or in the
speaker profiles (first name is enough), or an explicit --track "Roar=Roar
Granevang". Tracks that map to nobody are treated as non-speech. `--list`
prints the tracks and files and stops.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from asr_common import DEFAULT_AUDIO_LIBRARY, find_episode_audio, format_ts, setup_cuda_paths

HOST_TRACKS = {"mamen": "Mr. Mamen", "mr. mamen": "Mr. Mamen", "mr mamen": "Mr. Mamen",
               "sigve": "Sigve"}
NON_SPEECH_HINTS = ("musikk", "music", "intro", "outro", "sfx", "effekt", "lyd", "jingle",
                    "spill", "game", "klipp", "clip", "voices", "master")
DEFAULT_ITEM_MODEL = "Systran/faster-whisper-large-v3"   # multilingual, for clips
MIN_CLIP_SPEECH = 2.0    # seconds of VAD speech before a non-speaker file counts as a clip
MIN_CLIP_RATIO = 0.15    # ... and at least this share of the file
MIN_GAP = 2.5        # seconds of mix silence before solo words are inserted
MIN_GAP_WORDS = 4
WORD_PAD = 1.0       # items only count as fallback this far from any solo word


# --------------------------------------------------------------------------
# Reaper project
# --------------------------------------------------------------------------
def parse_rpp(path: Path) -> list[dict]:
    """Tracks as {"name", "mute", "items": [{pos, len, soffs, rate, mute, file}]}."""
    tracks: list[dict] = []
    cur = item = None
    stack: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("<"):
            tag = s.split()[0]
            stack.append(tag)
            if tag == "<TRACK":
                cur = {"name": "", "mute": 0, "items": []}
                tracks.append(cur)
            elif tag == "<ITEM" and cur is not None:
                item = {"pos": 0.0, "len": 0.0, "soffs": 0.0, "rate": 1.0, "mute": 0,
                        "file": None}
                cur["items"].append(item)
            continue
        if s == ">":
            stack.pop()
            if stack and stack[-1] == "<TRACK":
                item = None
            continue
        top = stack[-1] if stack else ""
        parts = s.split()
        if not parts:
            continue
        if top == "<TRACK" and cur is not None and item is None:
            if parts[0] == "NAME":
                cur["name"] = s[5:].strip().strip('"')
            elif parts[0] == "MUTESOLO":
                cur["mute"] = int(parts[1])
        elif item is not None and top == "<ITEM":
            if parts[0] == "POSITION":
                item["pos"] = float(parts[1])
            elif parts[0] == "LENGTH":
                item["len"] = float(parts[1])
            elif parts[0] == "SOFFS":
                item["soffs"] = float(parts[1])
            elif parts[0] == "PLAYRATE":
                item["rate"] = float(parts[1])
            elif parts[0] == "MUTE":
                item["mute"] = int(parts[1])
        elif item is not None and top == "<SOURCE" and parts[0] == "FILE":
            m = re.match(r'FILE\s+"([^"]*)"', s)      # FILE "name.mp3" 1  (trailing flags)
            item["file"] = m.group(1) if m else s[5:].strip()
    for t in tracks:
        t["items"] = [i for i in t["items"] if not i["mute"] and i["file"] and i["len"] > 0]
    return [t for t in tracks if not t["mute"]]


def find_rpp(folder: Path) -> Path | None:
    cands = [p for p in folder.iterdir()
             if p.suffix.lower() == ".rpp" and "newtemp" not in p.name.lower()]
    if not cands:
        return None
    return max(cands, key=lambda p: p.stat().st_mtime)


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def basename(win_path: str) -> str:
    return win_path.replace("\\", "/").rsplit("/", 1)[-1]


def resolve(folder: Path, fname: str) -> Path | None:
    name = _nfc(basename(fname)).lower()
    for cand in folder.iterdir():
        if _nfc(cand.name).lower() == name:
            return cand
    return None


# --------------------------------------------------------------------------
# Speaker mapping
# --------------------------------------------------------------------------
def known_people(project: Path, episode: int | None) -> list[str]:
    names: list[str] = []
    prof = project / "transcripts" / "speaker_profiles.npy"
    if prof.exists():
        try:
            import numpy as np
            names += list(np.load(prof, allow_pickle=True).item().keys())
        except Exception:
            pass
    if episode is not None:
        try:
            sys.path.insert(0, str(project / "scripts"))
            from transcribe import lookup_episode
            meta = lookup_episode(project, number=episode)
            names += list((meta or {}).get("people") or [])
        except Exception as e:  # metadata is a convenience only
            print(f"  (episode metadata unavailable: {e})")
    seen: dict[str, None] = {}
    for n in names:
        seen.setdefault(n, None)
    return list(seen)


def map_tracks(tracks: list[dict], people: list[str], overrides: dict[str, str]) -> dict[str, str]:
    """Track name -> full speaker name for the tracks that are a person."""
    out: dict[str, str] = {}
    for t in tracks:
        if not t["items"]:
            continue
        name = t["name"]
        low = name.lower().strip()
        if name in overrides:
            out[name] = overrides[name]
        elif low in HOST_TRACKS:
            out[name] = HOST_TRACKS[low]
        else:
            hits = [p for p in people
                    if low == p.lower() or low == p.split()[0].lower()
                    or low in p.lower()]
            if len(hits) == 1 and not any(h in low for h in NON_SPEECH_HINTS):
                out[name] = hits[0]
    return out


# --------------------------------------------------------------------------
# Transcription of clean files
# --------------------------------------------------------------------------
def ensure_cache(project: Path, audio: Path, tag: str, lang: str, episode: int | None,
                 no_transcribe: bool, model: str | None = None) -> dict:
    raw_dir = project / ".cache" / "raw"
    cache = raw_dir / f"{audio.stem}.{tag}.json"
    if not cache.exists():
        if no_transcribe:
            raise SystemExit(f"Missing {cache}; run transcribe.py --no-diarization on {audio}.")
        print(f"  Transcribing {audio.name} ({lang})...")
        cmd = [sys.executable, str(project / "scripts" / "transcribe.py"), str(audio),
               "-o", str(raw_dir / f"{audio.stem}.{tag}.vtt"), "--no-diarization",
               "--language", lang]
        if episode is not None:
            cmd += ["--episode-number", str(episode)]
        if model:
            cmd += ["--model", model]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            sys.stderr.write(r.stderr[-2000:])
            raise SystemExit(f"transcribe.py failed on {audio.name}")
    return json.loads(cache.read_text(encoding="utf-8"))


def speech_seconds(path: Path) -> tuple[float, float]:
    """(seconds of speech per Silero VAD, file duration)."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    from asr_common import load_audio, SAMPLE_RATE
    wav = load_audio(path)
    ts = get_speech_timestamps(wav, VadOptions(threshold=0.5, min_speech_duration_ms=500,
                                               min_silence_duration_ms=1000))
    return sum(s["end"] - s["start"] for s in ts) / SAMPLE_RATE, len(wav) / SAMPLE_RATE


# --------------------------------------------------------------------------
# Speaker stems: each microphone as heard in the mix
# --------------------------------------------------------------------------
STEM_MODEL = "TheStigh/nb-whisper-large-ct2"     # transcribe.py's default
STEM_VAD = dict(threshold=0.3, min_silence_duration_ms=2000, speech_pad_ms=600)
ENVELOPE_STEP = 0.1      # seconds per RMS value kept in the cache


def build_stems(folder: Path, files_by_speaker: dict) -> dict:
    """One mono 16 kHz track per speaker, every item placed at its mix position.

    This is the speaker's microphone exactly as it plays in the edited
    episode (fades and item volume aside), so its transcript needs no
    mapping and contains nothing that was cut.
    """
    import numpy as np
    from asr_common import SAMPLE_RATE, load_audio
    by_role: dict[str, list[tuple[Path, dict]]] = defaultdict(list)
    for (role, fname), items in files_by_speaker.items():
        path = resolve(folder, fname)
        if path is None:
            print(f"  ⚠ {role}: {fname} not in {folder}; its items are left out")
            continue
        by_role[role] += [(path, i) for i in items]
    stems = {}
    for role, placed in by_role.items():
        end = max(i["pos"] + i["len"] for _, i in placed)
        stem = np.zeros(int(end * SAMPLE_RATE) + SAMPLE_RATE, dtype=np.float32)
        cache: dict[Path, np.ndarray] = {}
        for path, i in placed:
            if path not in cache:
                cache[path] = load_audio(path)
            src = cache[path]
            a = int(i["soffs"] * SAMPLE_RATE)
            n_out = int(i["len"] * SAMPLE_RATE)
            seg = src[a:a + int(i["len"] * i["rate"] * SAMPLE_RATE)]
            if i["rate"] != 1.0 and len(seg):
                seg = np.interp(np.linspace(0, len(seg) - 1, n_out), np.arange(len(seg)), seg)
            o = int(i["pos"] * SAMPLE_RATE)
            seg = seg[:len(stem) - o]
            stem[o:o + len(seg)] += seg
        stems[role] = stem
        print(f"  stem {role:22s} {len(placed):4d} items from "
              f"{', '.join(sorted({p.name for p, _ in placed}))[:70]}")
    return stems


def _segments(segs, offset: float = 0.0, tag: str = "") -> list[dict]:
    out = []
    for s in segs:
        if "<|" in s.text or not s.words:
            continue
        out.append({"start": s.start + offset, "end": s.end + offset, "text": s.text.strip(),
                    "words": [{"start": w.start + offset, "end": w.end + offset, "word": w.word}
                              for w in s.words], "pass": tag})
    return out


def transcribe_stem(model, wav) -> list[dict]:
    """Transcribe one stem in three passes; Whisper drops speech in long files.

    1. sequential decoding (best text);
    2. batched decoding, keeping only runs of words the first pass has
       nothing for within 1 s (4+ words or 2.5+ s);
    3. every stretch of >= 2 s that Silero VAD calls speech and that still
       has no word is transcribed on its own.
    """
    import bisect
    from faster_whisper import BatchedInferencePipeline
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    from asr_common import SAMPLE_RATE
    kw = dict(language="no", beam_size=5, word_timestamps=True, vad_filter=True,
              vad_parameters=STEM_VAD)
    segs = _segments(model.transcribe(wav, **kw)[0], tag="seq")

    have = sorted(w["start"] for s in segs for w in s["words"])
    def near(t: float, pad: float) -> bool:
        i = bisect.bisect_left(have, t - pad)
        return i < len(have) and have[i] <= t + pad
    batched = _segments(BatchedInferencePipeline(model=model).transcribe(wav, batch_size=8, **kw)[0])
    runs, cur = [], []
    for w in (w for s in batched for w in s["words"]):
        if near(w["start"], 1.0):
            if cur:
                runs.append(cur)
            cur = []
        else:
            cur.append(w)
    if cur:
        runs.append(cur)
    for r in runs:
        if len(r) >= 4 or r[-1]["end"] - r[0]["start"] >= 2.5:
            segs.append({"start": r[0]["start"], "end": r[-1]["end"],
                         "text": "".join(w["word"] for w in r).strip(), "words": r,
                         "pass": "batched"})

    have = sorted(w["start"] for s in segs for w in s["words"])
    spans = get_speech_timestamps(wav, VadOptions(threshold=0.5, min_silence_duration_ms=700,
                                                  speech_pad_ms=200))
    todo = []
    for sp in spans:
        a, e = sp["start"] / SAMPLE_RATE, sp["end"] / SAMPLE_RATE
        if e - a < 1.5:
            continue
        run = None
        for b in range(int(a), int(e) + 1):
            miss = not near(b + 0.5, 1.0)
            if miss:
                run = [b, b + 1] if run is None else [run[0], b + 1]
            if (not miss or b == int(e)) and run is not None:
                if run[1] - run[0] >= 2:
                    todo.append((max(a, run[0]), min(e, run[1])))
                run = None
    for a, e in todo:
        lo = max(0.0, a - 0.3)
        piece = wav[int(lo * SAMPLE_RATE):int((e + 0.3) * SAMPLE_RATE)]
        segs += _segments(model.transcribe(piece, language="no", beam_size=5, word_timestamps=True,
                                           vad_filter=True,
                                           vad_parameters=dict(threshold=0.3, speech_pad_ms=300))[0],
                          offset=lo, tag="span")
    segs.sort(key=lambda s: s["start"])
    return segs


def envelope(wav) -> list[float]:
    import numpy as np
    from asr_common import SAMPLE_RATE
    h = int(ENVELOPE_STEP * SAMPLE_RATE)
    x = wav[:len(wav) // h * h].reshape(-1, h)
    return [round(float(v), 4) for v in np.sqrt((x ** 2).mean(axis=1))]


def stem_transcripts(project: Path, folder: Path, rpp: Path, files_by_speaker: dict,
                     out_stem: str, redo: bool) -> dict:
    """{speaker: {"segments", "envelope"}}, cached in .cache/raw/<stem>.stems.json."""
    cache = project / ".cache" / "raw" / f"{out_stem}.stems.json"
    key = {"rpp": rpp.name, "rpp_mtime": rpp.stat().st_mtime,
           "files": sorted(f"{r}|{f}|{len(i)}" for (r, f), i in files_by_speaker.items())}
    if cache.exists() and not redo:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("key") == key:
            print(f"  using {cache.relative_to(project)} (--redo-stems to transcribe again)")
            return data["speakers"]
        print(f"  {cache.name} is from another project state; transcribing again")
    from faster_whisper import WhisperModel
    stems = build_stems(folder, files_by_speaker)
    model = WhisperModel(STEM_MODEL, device="cuda", compute_type="float16")
    speakers = {}
    for role, wav in stems.items():
        segs = transcribe_stem(model, wav)
        per = Counter(s["pass"] for s in segs)
        words = Counter()
        for s in segs:
            words[s["pass"]] += len(s["words"])
        print(f"  {role:22s} {sum(words.values()):5d} words "
              f"(sequential {words['seq']}, batched fill {words['batched']}, "
              f"speech spans {words['span']} in {per['span']} spans)")
        speakers[role] = {"segments": segs, "envelope": envelope(wav)}
    cache.write_text(json.dumps({"key": key, "speakers": speakers}, ensure_ascii=False),
                     encoding="utf-8")
    return speakers


def build_from_stems(mix_path: Path, speakers: dict, speaker_items: list[dict],
                     inserts: list[dict], non_speech: list[tuple[float, float]]) -> dict:
    """Raw cache whose text comes from the stems; every segment carries its speaker."""
    import av
    with av.open(str(mix_path)) as c:
        duration = (c.duration or 0) / 1_000_000
    segs, diar = [], []
    for role, d in speakers.items():
        for s in d["segments"]:
            segs.append({**s, "speaker": role})
            diar.append({"start": s["start"], "end": s["end"], "speaker": role})
    for ins in inserts:
        for s in ins["segments"]:
            segs.append({**s, "speaker": ins["speaker"]})
        diar.append({"start": ins["start"], "end": ins["end"], "speaker": ins["speaker"]})
        print(f"  {ins['speaker']:22s} {format_ts(ins['start'])} - {format_ts(ins['end'])}: "
              f"{len(ins['segments'])} segment(s) from the clean file")
    segs.sort(key=lambda s: s["start"])
    diar.sort(key=lambda d: d["start"])
    # microphone items with no word at all: a dropout or speech the passes missed
    words = sorted(w["start"] for s in segs for w in s["words"])
    import bisect
    silent = []
    for it in speaker_items:
        if it["end"] - it["start"] < 3.0:
            continue
        i = bisect.bisect_left(words, it["start"])
        if i >= len(words) or words[i] > it["end"]:
            env = speakers.get(it["speaker"], {}).get("envelope") or []
            a, b = int(it["start"] / ENVELOPE_STEP), int(it["end"] / ENVELOPE_STEP)
            loud = max(env[a:b], default=0.0)
            if loud > 0.02:
                silent.append((it["start"], it["end"], it["speaker"], loud))
    if silent:
        print(f"  {len(silent)} microphone item(s) >= 3 s with sound but no words "
              f"(listen; laughter, or speech every pass missed):")
        for a, b, who, loud in silent:
            print(f"    {format_ts(a)} - {format_ts(b)} {who}")
    names = {s["speaker"] for s in segs}
    return {"audio": str(mix_path), "duration": duration, "language": "no", "stems": True,
            "segments": segs, "diarization": diar, "speaker_map": {n: n for n in names},
            "gap_review": [],
            "solo_segments": [{**s, "speaker": role} for role, d in speakers.items()
                              for s in d["segments"]],
            "stem_envelope": {role: d["envelope"] for role, d in speakers.items()},
            "envelope_step": ENVELOPE_STEP,
            "non_speech_spans": [[a, b] for a, b in non_speech]}


# --------------------------------------------------------------------------
# Mapping solo words into the mix (--mix-text)
# --------------------------------------------------------------------------
def map_words(raw: dict, items: list[dict], speaker: str) -> tuple[list[dict], int]:
    """Solo words -> mix time through the items of their file. Returns (words, dropped)."""
    items = sorted(items, key=lambda i: i["soffs"])
    out, dropped = [], 0
    for seg in raw["segments"]:
        for w in seg["words"]:
            mid = (w["start"] + w["end"]) / 2
            it = next((i for i in items if i["soffs"] <= mid < i["soffs"] + i["len"] * i["rate"]),
                      None)
            if it is None:
                dropped += 1
                continue
            def to_mix(t: float, it: dict = it) -> float:
                return it["pos"] + (t - it["soffs"]) / it["rate"]
            out.append({"start": to_mix(w["start"]), "end": to_mix(w["end"]), "word": w["word"],
                        "speaker": speaker, "_item": id(it)})
    return out, dropped


def words_to_segments(words: list[dict], max_words: int = 40, max_pause: float = 1.0) -> list[dict]:
    segs: list[dict] = []
    for w in sorted(words, key=lambda w: w["start"]):
        cur = segs[-1] if segs else None
        if (cur and cur["speaker"] == w["speaker"] and cur["_item"] == w["_item"]
                and w["start"] - cur["end"] < max_pause and len(cur["words"]) < max_words):
            cur["words"].append(w)
            cur["end"] = w["end"]
        else:
            segs.append({"start": w["start"], "end": w["end"], "speaker": w["speaker"],
                         "_item": w["_item"], "words": [w]})
    for s in segs:
        s["text"] = "".join(w["word"] for w in s["words"]).strip()
        s["words"] = [{"start": w["start"], "end": w["end"], "word": w["word"]} for w in s["words"]]
        del s["_item"]
    return segs


def split_segment_at(segs: list[dict], lo: float, hi: float) -> list[dict]:
    """Split any segment spanning [lo, hi] so its cues render in time order."""
    out = []
    for s in segs:
        if s["start"] < lo and s["end"] > hi and s.get("words"):
            before = [w for w in s["words"] if w["end"] <= lo]
            after = [w for w in s["words"] if w["start"] >= hi]
            if before and after and len(before) + len(after) == len(s["words"]):
                for part in (before, after):
                    out.append({**s, "start": part[0]["start"], "end": part[-1]["end"],
                                "text": "".join(w["word"] for w in part).strip(), "words": part})
                continue
        out.append(s)
    return out


def subtract(span: tuple[float, float], covered: list[tuple[float, float]]) -> list[tuple[float, float]]:
    a, b = span
    out = []
    cur = a
    for x, y in covered:
        if y <= cur:
            continue
        if x >= b:
            break
        if x > cur:
            out.append((cur, x))
        cur = max(cur, y)
    if cur < b:
        out.append((cur, b))
    return out


def merge_spans(spans: list[tuple[float, float]], gap: float = 0.5) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(spans):
        if out and a - out[-1][1] < gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


TAIL_MAX_PAUSE = 0.7  # solo words this close after the last mix word continue its sentence


def _norm_word(s: str) -> str:
    return re.sub(r"[^\wæøå]", "", s.lower())


def fill_tails(segs: list[dict], sw: list[dict]) -> list[tuple[dict, list[dict]]]:
    """Append to each segment the solo words that continue its last word's speaker.

    The last mix word's speaker is the solo word overlapping it most. From
    there, solo words of that speaker are taken while each starts within
    TAIL_MAX_PAUSE of the previous one, no other speaker's word comes in
    between, and they end before the next mix word starts. A solo word that
    is the mix word itself (same text, overlapping) is skipped. Segments are
    modified in place; returns [(segment, added words)].
    """
    import bisect
    starts = [w["start"] for w in sw]
    order = sorted(segs, key=lambda s: s["start"])
    next_seg = {id(s): n for s, n in zip(order, order[1:] + [None])}
    next_start = {k: (n["start"] if n is not None else float("inf")) for k, n in next_seg.items()}
    added = []
    for s in order:
        words = s.get("words") or []
        real = [w for w in words if _norm_word(w["word"])]
        if not real:
            continue
        last = real[-1]
        lo = bisect.bisect_left(starts, last["start"] - 2.0)
        near = sw[lo:bisect.bisect_left(starts, last["end"] + 0.5)]
        over = [(min(w["end"], last["end"]) - max(w["start"], last["start"]), w) for w in near]
        over = [o for o in over if o[0] > 0]
        if not over:
            continue
        spk = max(over, key=lambda o: o[0])[1]["speaker"]
        limit = min(next_start[id(s)], words[-1]["end"] + 30)
        run: list[dict] = []
        prev_end = words[-1]["end"]
        for w in sw[bisect.bisect_left(starts, words[-1]["end"] - 0.3):]:
            if w["start"] >= limit or w["end"] > limit + 0.1:
                break
            if w["end"] <= words[-1]["end"] + 0.05:
                continue
            if w["speaker"] != spk:
                break
            if w["start"] - prev_end > TAIL_MAX_PAUSE:
                break
            if (not run and w["start"] < last["end"]
                    and _norm_word(w["word"]) == _norm_word(last["word"])):
                prev_end = max(prev_end, w["end"])
                continue
            run.append(w)
            prev_end = w["end"]
        # the solo and mix clocks differ by a few hundred ms, so the tail can be the
        # next segment's opening words heard early: drop that overlap
        nxt = next_seg[id(s)]
        if run and nxt is not None:
            head = [t for t in (_norm_word(w["word"]) for w in nxt.get("words") or []) if t]
            toks = [_norm_word(w["word"]) for w in run]
            for k in range(len(run), 0, -1):
                tail = [t for t in toks[-k:] if t]
                if tail and head[:len(tail)] == tail:
                    run = run[:-k]
                    break
        if not [w for w in run if _norm_word(w["word"])]:
            continue
        s["words"] = words + [{"start": w["start"], "end": w["end"], "word": w["word"]}
                              for w in run]
        s["end"] = run[-1]["end"]
        s["text"] = "".join(w["word"] for w in s["words"]).strip()
        added.append((s, run))
    return added


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------
def build(raw: dict, speaker_words: list[dict], speaker_items: list[dict],
          inserts: list[dict], non_speech: list[tuple[float, float]]) -> dict:
    segs = [dict(s) for s in raw["segments"]]
    diar: list[dict] = []

    # 0) words the mix ASR produced inside music/effects spans, with no microphone
    #    item and no solo word within 1 s, are hallucinations or game audio
    sw_all = sorted(speaker_words, key=lambda w: w["start"])
    support = merge_spans([(w["start"] - 1.0, w["end"] + 1.0) for w in sw_all]
                          + [(i["start"] - 1.0, i["end"] + 1.0) for i in speaker_items], gap=0)
    def supported(t):
        return any(a <= t <= b for a, b in support)
    def in_non_speech(t):
        return any(a <= t <= b for a, b in non_speech)
    dropped_words = []
    kept = []
    for s in segs:
        words = s.get("words") or []
        good = [w for w in words if not (in_non_speech((w["start"] + w["end"]) / 2)
                                         and not supported((w["start"] + w["end"]) / 2))]
        if len(good) == len(words):
            kept.append(s)
            continue
        dropped_words += [w for w in words if w not in good]
        if good:
            kept.append({**s, "start": good[0]["start"], "end": good[-1]["end"],
                         "text": "".join(w["word"] for w in good).strip(), "words": good})
    segs = kept
    if dropped_words:
        print(f"  dropped {len(dropped_words)} mix word(s) inside music/effects spans with no "
              f"microphone support (hallucination or game audio):")
        run: list[dict] = []
        for w in dropped_words + [None]:
            if w is None or (run and w["start"] - run[-1]["end"] > 2.0):
                if run:
                    print(f"    {format_ts(run[0]['start'])} "
                          f"{''.join(x['word'] for x in run).strip()[:80]}")
                run = []
            if w is not None:
                run.append(w)

    # 1) clean non-speaker items (game intro etc.) replace the mix text in their span;
    #    two clips that overlap in the mix: the earlier one is cut where the next starts
    inserts.sort(key=lambda i: i["start"])
    for prev, nxt in zip(inserts, inserts[1:]):
        if prev["end"] > nxt["start"]:
            cut = nxt["start"]
            prev["segments"] = [
                {**s, "words": [w for w in s["words"] if w["start"] < cut]}
                for s in prev["segments"] if s["start"] < cut]
            for s in prev["segments"]:
                s["end"] = min(s["end"], cut)
                s["text"] = "".join(w["word"] for w in s["words"]).strip()
            prev["segments"] = [s for s in prev["segments"] if s["words"]]
            prev["end"] = cut
    for ins in inserts:
        lo, hi = ins["start"] - 0.5, ins["end"] + 0.5
        n0 = len(segs)
        segs = [s for s in segs if s["end"] <= lo or s["start"] >= hi]
        segs = split_segment_at(segs, lo, hi)
        segs += ins["segments"]
        diar.append({"start": lo, "end": hi, "speaker": ins["speaker"]})
        print(f"  {ins['speaker']:22s} {format_ts(ins['start'])} - {format_ts(ins['end'])}: "
              f"replaced {n0 - len(segs) + len(ins['segments'])} mix segment(s) "
              f"with {len(ins['segments'])} from the clean file")

    # 2) solo words as diarization
    sw = sorted(speaker_words, key=lambda w: w["start"])
    diar += [{"start": w["start"], "end": w["end"], "speaker": w["speaker"]} for w in sw]

    # 3) Reaper items as fallback where no solo word is near
    covered = merge_spans([(w["start"] - WORD_PAD, w["end"] + WORD_PAD) for w in sw], gap=0)
    covered += [(i["start"] - 0.5, i["end"] + 0.5) for i in inserts]
    covered = merge_spans(covered, gap=0)
    n_fb = 0
    dropouts = []
    for it in speaker_items:
        for a, b in subtract((it["start"], it["end"]), covered):
            if b - a > 0.3:
                diar.append({"start": a, "end": b, "speaker": it["speaker"]})
                n_fb += 1
                if b - a >= 3.0:
                    dropouts.append((a, b, it["speaker"]))
    diar.sort(key=lambda d: d["start"])
    if dropouts:
        print(f"  {len(dropouts)} microphone item span(s) >= 3 s without solo words "
              f"(solo-track dropout; tags there come from the item, check them):")
        for a, b, who in sorted(dropouts):
            print(f"    {format_ts(a)} - {format_ts(b)} {who}")

    # 4a) tails: the mix ASR often stops a sentence early ("… grid" with the solo
    #     track going on "to prefectures"). Solo words that continue the speaker of
    #     the last mix word without a pause belong to that segment, however short
    #     the gap is.
    tails = fill_tails(segs, sw)
    if tails:
        print(f"  sentence tails added from solo: {len(tails)} "
              f"({sum(len(t[1]) for t in tails)} words)")
        for s, run in tails[:15]:
            print(f"    {format_ts(run[0]['start'])} {run[0]['speaker'][:12]:12s} "
                  f"…{s['text'][-30:]}")
        if len(tails) > 15:
            print(f"    … and {len(tails) - 15} more")

    # 4b) gaps in the mix text filled from solo words
    mw = sorted((w for s in segs for w in s.get("words", [])), key=lambda w: w["start"])
    bounds = [(0.0, mw[0]["start"])] + [(a["end"], b["start"]) for a, b in zip(mw, mw[1:])]
    bounds.append((mw[-1]["end"], raw.get("duration", mw[-1]["end"] + 1)))
    fills: list[list[dict]] = []
    for a, b in bounds:
        if b - a < MIN_GAP:
            continue
        inside = [w for w in sw if a + 0.3 <= w["start"] and w["end"] <= b - 0.3]
        run: list[dict] = []
        for w in inside:
            if run and (w["speaker"] != run[-1]["speaker"] or w["start"] - run[-1]["end"] > 2.0):
                if len(run) >= MIN_GAP_WORDS:
                    fills.append(run)
                run = []
            run.append(w)
        if len(run) >= MIN_GAP_WORDS:
            fills.append(run)
    fills.sort(key=lambda r: r[0]["start"])
    for prev, nxt in zip(fills, fills[1:]):      # overlapping voices: clip the earlier one
        if prev[-1]["end"] > nxt[0]["start"]:
            prev[-1] = {**prev[-1], "end": nxt[0]["start"]}
    for run in fills:
        lo, hi = run[0]["start"], run[-1]["end"]
        segs = split_segment_at(segs, lo, hi)
        segs.append({"start": lo, "end": hi,
                     "text": "".join(w["word"] for w in run).strip(),
                     "words": [{"start": w["start"], "end": w["end"], "word": w["word"]} for w in run],
                     "solo_fill": True})
    segs.sort(key=lambda s: s["start"])
    fill_s = sum(r[-1]["end"] - r[0]["start"] for r in fills)
    print(f"  solo words as turns: {len(sw)}, item fallback spans: {n_fb}, "
          f"gaps filled from solo: {len(fills)} ({fill_s:.0f} s, "
          f"{sum(len(r) for r in fills)} words)")
    for r in fills:
        print(f"    {format_ts(r[0]['start'])} {r[0]['speaker'][:12]:12s} "
              f"{''.join(w['word'] for w in r).strip()[:80]}")

    # 5) cues that no speaker supports: likely game audio / hallucination
    speaker_cover = merge_spans([(w["start"], w["end"]) for w in sw]
                                + [(i["start"], i["end"]) for i in speaker_items]
                                + [(i["start"], i["end"]) for i in inserts])
    orphans = []
    for s in segs:
        if s.get("solo_fill"):
            continue
        if not any(min(s["end"], b) - max(s["start"], a) > 0.2 for a, b in speaker_cover):
            in_ns = any(min(s["end"], b) - max(s["start"], a) > 0 for a, b in non_speech)
            orphans.append((s, in_ns))
    if orphans:
        print(f"  {len(orphans)} segment(s) outside every speaker item "
              f"(M = inside a music/effects item; check for game audio or hallucination):")
        for s, in_ns in orphans:
            print(f"    {format_ts(s['start'])} {'M' if in_ns else ' '} {s['text'][:80]}")

    smap = {w["speaker"]: w["speaker"] for w in sw}
    smap.update({i["speaker"]: i["speaker"] for i in speaker_items})
    smap.update({i["speaker"]: i["speaker"] for i in inserts})
    solo_segments = words_to_segments(
        [{**w, "_item": w.get("_item", 0)} for w in sw])
    return {**raw, "segments": segs, "diarization": diar, "speaker_map": smap,
            "solo_segments": solo_segments,
            "non_speech_spans": [[a, b] for a, b in non_speech],
            "diarization_pyannote": raw.get("diarization"),
            "speaker_map_pyannote": raw.get("speaker_map")}


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
    ap.add_argument("--rpp", type=Path, help="Reaper project (default: newest .rpp in the folder)")
    ap.add_argument("--track", action="append", default=[],
                    help='"<track name>=<Full speaker name>" (repeatable)')
    ap.add_argument("--item", action="append", default=[],
                    help='"<file>=<Tag>[|lang]": tag (and language) for a clip, also for a '
                         'produced clip on a speaker track (not that microphone); files not listed are still found automatically and tagged '
                         '"Spillklipp" with the language detected (repeatable)')
    ap.add_argument("--no-auto-items", action="store_true",
                    help="Only transcribe the clips given with --item")
    ap.add_argument("--min-clip-speech", type=float, default=MIN_CLIP_SPEECH,
                    help=f"Seconds of VAD speech for a non-speaker file to count as a clip "
                         f"(default {MIN_CLIP_SPEECH}, and at least {MIN_CLIP_RATIO * 100:.0f}%% of it)")
    ap.add_argument("--item-model", default=DEFAULT_ITEM_MODEL,
                    help="Whisper model for --item files in another language than Norwegian "
                         f"(default: {DEFAULT_ITEM_MODEL}). NB-Whisper translates English "
                         "clips into Norwegian even with --language en.")
    ap.add_argument("--list", action="store_true", help="Print tracks, items and files; stop")
    ap.add_argument("--no-transcribe", action="store_true",
                    help="Fail instead of transcribing solo files whose cache is missing")
    ap.add_argument("--mix-text", action="store_true",
                    help="Old mode: keep the mix transcript from transcribe.py and only take "
                         "speakers and gap fills from the raw solo files")
    ap.add_argument("--redo-stems", action="store_true",
                    help="Transcribe the speaker stems again even if .cache/raw/<stem>.stems.json "
                         "matches the project")
    args = ap.parse_args()
    if not args.list and not args.mix_text:
        setup_cuda_paths()          # re-execs once so ctranslate2 finds the CUDA libraries

    project = Path(__file__).resolve().parent.parent
    mix_path = find_episode_audio(args.episode_number, args.library)
    folder = mix_path.parent
    rpp = args.rpp or find_rpp(folder)
    if rpp is None:
        sys.stderr.write(f"No .rpp in {folder}\n")
        return 1
    print(f"Reaper project: {rpp.name}")
    tracks = parse_rpp(rpp)

    overrides = dict(p.partition("=")[::2] for p in args.track)
    overrides = {k.strip(): v.strip() for k, v in overrides.items()}
    people = known_people(project, args.episode_number)
    who = map_tracks(tracks, people, overrides)

    speaker_items: list[dict] = []
    non_speech: list[tuple[float, float]] = []
    files_by_speaker: dict[tuple[str, str], list[dict]] = defaultdict(list)
    specs: dict[str, tuple[str, str]] = {}          # file -> (tag, lang)
    for spec in args.item:
        fname, _, tag = spec.partition("=")
        tag, _, lang = tag.partition("|")
        specs[_nfc(fname.strip()).lower()] = (tag.strip() or "Spillklipp", lang.strip() or "auto")
    for t in tracks:
        if not t["items"]:
            continue
        total = sum(i["len"] for i in t["items"])
        files = sorted({basename(i["file"]) for i in t["items"]})
        role = who.get(t["name"])
        print(f"  track {t['name']!r:24s} {len(t['items']):4d} items {total / 60:6.1f} min  "
              f"-> {role or 'non-speech'}   files: {', '.join(files)[:90]}")
        for i in t["items"]:
            span = {"start": i["pos"], "end": i["pos"] + i["len"]}
            if role and _nfc(basename(i["file"])).lower() not in specs:
                speaker_items.append({**span, "speaker": role})
                files_by_speaker[(role, basename(i["file"]))].append(i)
            else:
                non_speech.append((span["start"], span["end"]))
    non_speech = merge_spans(non_speech)
    # A recording belongs to one microphone. When a file also appears on another
    # speaker's track (an item dragged onto the wrong track), tag those items with
    # the owner, i.e. the speaker whose track uses the file most.
    use: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for (role, fname), items in files_by_speaker.items():
        use[fname][role] += sum(i["len"] for i in items)
    for fname, by_role in use.items():
        if len(by_role) < 2:
            continue
        owner = max(by_role, key=by_role.get)
        for role in [r for r in by_role if r != owner]:
            moved = files_by_speaker.pop((role, fname))
            files_by_speaker[(owner, fname)] += moved
            for i in moved:
                for si in speaker_items:
                    if si["speaker"] == role and si["start"] == i["pos"]:
                        si["speaker"] = owner
            print(f"  ⚠ {fname}: {len(moved)} item(s) ({sum(i['len'] for i in moved):.0f} s) on the "
                  f"{role!r} track belong to {owner}'s microphone; tagged {owner}")
    if args.list:
        return 0
    if not who:
        sys.stderr.write("No speaker tracks recognised; give --track NAME=Full Name.\n")
        return 1

    # solo tracks (--mix-text only; the stems are built further down)
    speaker_words: list[dict] = []
    for (role, fname), items in sorted(files_by_speaker.items() if args.mix_text else []):
        path = resolve(folder, fname)
        if path is None:
            print(f"  ⚠ {role}: {fname} not in {folder}; using Reaper items only for it")
            continue
        raw = ensure_cache(project, path, "solo", "no", args.episode_number, args.no_transcribe)
        words, dropped = map_words(raw, items, role)
        speaker_words += words
        print(f"  {role:22s} {path.name}: {len(words)} words in the mix, {dropped} cut out")

    # clips: files on non-speaker tracks that contain speech, and --item files
    # wherever they lie
    ns_files: dict[str, list[dict]] = defaultdict(list)
    for t in tracks:
        for i in t["items"]:
            key = _nfc(basename(i["file"])).lower()
            if not who.get(t["name"]) or key in specs:
                ns_files[key].append(i)
    if not args.no_auto_items:
        for key, items in sorted(ns_files.items()):
            if key in specs:
                continue
            path = resolve(folder, key)
            if path is None:
                continue
            try:
                speech, dur = speech_seconds(path)
            except Exception as e:
                print(f"  ⚠ {path.name}: VAD failed ({e})")
                continue
            if speech >= args.min_clip_speech and speech / max(dur, 0.1) >= MIN_CLIP_RATIO:
                specs[key] = ("Spillklipp", "auto")
                print(f"  clip {path.name}: {speech:.0f} s speech of {dur:.0f} s "
                      f"({len(items)} item(s))")
            else:
                print(f"  music/effects {path.name}: {speech:.0f} s speech of {dur:.0f} s, skipped")
    for key in [k for k in specs if k not in ns_files]:
        print(f"  ⚠ --item {key}: no item with that file in the project")
    inserts: list[dict] = []
    for key, (tag, lang) in specs.items():
        occurrences = ns_files.get(key)
        if not occurrences:
            continue
        path = resolve(folder, key)
        if path is None:
            print(f"  ⚠ {key}: not in {folder}")
            continue
        raw = ensure_cache(project, path, "item", lang, args.episode_number, args.no_transcribe,
                           model=None if lang == "no" else args.item_model)
        detected = raw.get("language") or lang
        nwords = sum(len(s["words"]) for s in raw["segments"])
        print(f"  {tag:14s} {path.name}: {nwords} words, language {detected}")
        for it in occurrences:
            words, _ = map_words(raw, [it], tag)
            if not words:
                continue
            segs = words_to_segments([{**w, "_item": 0} for w in words])
            for s in segs:
                del s["speaker"]
            inserts.append({"start": words[0]["start"], "end": words[-1]["end"],
                            "speaker": tag, "segments": segs})

    raw_dir = project / ".cache" / "raw"
    raw_path = raw_dir / (args.output.stem + ".json")
    if not args.mix_text:
        print("Speaker stems...")
        speakers = stem_transcripts(project, folder, rpp, files_by_speaker, args.output.stem,
                                    args.redo_stems)
        if raw_path.exists():
            old = json.loads(raw_path.read_text(encoding="utf-8"))
            if not old.get("stems"):
                keep = raw_path.with_suffix(".mix.json")
                shutil.copy(raw_path, keep)
                print(f"  kept the earlier mix-based cache as {keep.name}")
        out = build_from_stems(mix_path, speakers, speaker_items, inserts, non_speech)
        raw_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {raw_path.relative_to(project)}. Render with:\n"
              f"  uv run python scripts/transcribe.py -o {args.output} --render-only")
        return 0
    if not raw_path.exists():
        sys.stderr.write(f"No raw cache {raw_path}; run transcribe.py -o {args.output} first.\n")
        return 1
    orig = raw_path.with_suffix(".orig.json")
    if not orig.exists():
        shutil.copy(raw_path, orig)
    print(f"Merging into {raw_path.relative_to(project)} (from {orig.name})...")
    out = build(json.loads(orig.read_text(encoding="utf-8")), speaker_words, speaker_items,
                inserts, non_speech)
    raw_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"Done. Re-render with:\n  uv run python scripts/transcribe.py -o {args.output} --render-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
