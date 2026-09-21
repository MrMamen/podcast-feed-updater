#!/usr/bin/env python3
"""Transcribe a podcast MP3 with NB-Whisper + optional pyannote diarization.

Output: WebVTT with sentence cues, optional <v Speaker> tags.

Requires:
  - NVIDIA GPU with CUDA drivers
  - HF_TOKEN in .env (only for diarization; accept pyannote licenses)
  - the project venv (`uv sync`), which bundles the CUDA wheels

Usage:
    uv run python scripts/transcribe.py <audio.mp3> -o output.vtt
    uv run python scripts/transcribe.py <audio.mp3> -o output.vtt --no-diarization
    uv run python scripts/transcribe.py <audio.mp3> -o output.vtt \\
        --initial-prompt "Names and terms to bias ASR toward: ..."
    uv run python scripts/transcribe.py <audio.mp3> -o output.vtt \\
        --speakers 3 --speaker-map "SPEAKER_01=Sigve,SPEAKER_00=Mr. Mamen"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from asr_common import (
    DEFAULT_AUDIO_LIBRARY,
    DEFAULT_DIARIZATION_MODEL,
    PROFILE_THRESHOLD,
    apply_corrections,
    find_episode_audio,
    format_ts,
    load_audio,
    load_corrections,
    load_diarization_pipeline,
    load_hf_token,
    match_profiles,
    run_diarization,
    setup_cuda_paths,
    speaker_for_range,
    speaker_totals,
)

setup_cuda_paths()


# --------------------------------------------------------------------------
# Transcription (NB-Whisper)
# --------------------------------------------------------------------------
def transcribe(audio_wav, *, model_name: str, language: str = "no",
               initial_prompt: str | None = None, beam_size: int = 5,
               vad_threshold: float | None = 0.3,
               batched: bool = False, batch_size: int = 8):
    from faster_whisper import WhisperModel

    print(f"Loading Whisper: {model_name}")
    t0 = time.time()
    model = WhisperModel(model_name, device="cuda", compute_type="float16")
    print(f"  loaded in {time.time()-t0:.1f}s")

    print(f"Transcribing ({len(audio_wav)/16000/60:.1f} min audio)...")
    t0 = time.time()
    kwargs = dict(language=language, beam_size=beam_size,
                  word_timestamps=True)
    # VAD trims non-speech, but the Silero default (threshold 0.5) is
    # aggressive enough to drop quiet or music-bedded speech entirely —
    # which leaves gaps in the transcript and breaks audio alignment.
    # Use a lower threshold plus generous padding so soft speech survives;
    # vad_threshold=None disables VAD completely (may hallucinate in silence).
    if vad_threshold is None:
        kwargs["vad_filter"] = False
        print("  VAD: disabled")
    else:
        kwargs["vad_filter"] = True
        kwargs["vad_parameters"] = dict(
            threshold=vad_threshold,
            min_silence_duration_ms=2000,
            speech_pad_ms=600,
        )
        print(f"  VAD: threshold={vad_threshold}, speech_pad_ms=600")
    if initial_prompt:
        kwargs["initial_prompt"] = initial_prompt

    if batched:
        # BatchedInferencePipeline decodes several VAD chunks in parallel;
        # typically 3-4x faster on GPU at the cost of more VRAM.
        from faster_whisper import BatchedInferencePipeline
        print(f"  mode: batched (batch_size={batch_size})")
        runner = BatchedInferencePipeline(model=model)
        segments, info = runner.transcribe(audio_wav, batch_size=batch_size, **kwargs)
    else:
        segments, info = model.transcribe(audio_wav, **kwargs)
    segs = list(segments)
    elapsed = time.time() - t0
    print(f"  {len(segs)} segments in {elapsed:.1f}s "
          f"({info.duration/elapsed:.1f}x realtime)")
    return segs, info.duration, model


# --------------------------------------------------------------------------
# Gap filling
# --------------------------------------------------------------------------
def fill_gaps(model, audio_wav, segs, *, language: str = "no",
              initial_prompt: str | None = None, min_gap: float = 3.0,
              min_speech: float = 1.5, substantive_words: int = 4,
              substantive_seconds: float = 2.5, sample_rate: int = 16000):
    """Re-transcribe stretches Whisper skipped but Silero VAD says contain speech.

    Whisper decodes VAD chunks of up to 30 s independently and sometimes
    stops early inside a chunk (speaker change, overlap) or never sees
    quiet speech the chunking VAD dropped. On a full episode that lost
    whole sentences. Running the model on just the gap, with no VAD and no
    chunk boundary, recovers them reliably.

    Returns (extra, review): ``extra`` are segment dicts worth inserting
    (at least ``substantive_words`` words or ``substantive_seconds`` long);
    ``review`` are short interjections ("Ja.", "Og ...") that the subtitle
    style usually omits, returned for the operator to judge.
    """
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    sr = sample_rate
    duration = len(audio_wav) / sr
    speech = [(s["start"] / sr, s["end"] / sr) for s in get_speech_timestamps(
        audio_wav, VadOptions(threshold=0.3, min_silence_duration_ms=500, speech_pad_ms=200))]

    def speech_in(a, b):
        return sum(max(0.0, min(e, b) - max(s, a)) for s, e in speech)

    # Gap edges come from the actual first/last word times, not segment
    # bounds: a segment's end often extends through a pause past its last
    # word, which would hide the first word of a skipped passage.
    def first_word(s):
        w = getattr(s, "words", None)
        return w[0].start if w else s.start

    def last_word(s):
        w = getattr(s, "words", None)
        return w[-1].end if w else s.end

    ordered = sorted(segs, key=lambda s: s.start)
    bounds = [(0.0, first_word(ordered[0]))] if ordered else [(0.0, duration)]
    bounds += [(last_word(a), first_word(b)) for a, b in zip(ordered, ordered[1:])]
    if ordered:
        bounds.append((last_word(ordered[-1]), duration))
    cands = []
    for a, b in bounds:
        if b - a >= min_gap:
            sp = speech_in(a, b)
            if sp >= min_speech:
                cands.append((a, b, sp))
    print(f"Gap check: {len(cands)} gaps >= {min_gap:.0f}s with speech "
          f"({sum(sp for _, _, sp in cands):.0f}s total)")

    extra, review = [], []
    for a, b, sp in cands:
        pa, pb = max(0.0, a - 0.3), min(duration, b + 0.3)
        clip = audio_wav[int(pa * sr):int(pb * sr)]
        segments, _ = model.transcribe(clip, language=language, beam_size=5,
                                       word_timestamps=True, vad_filter=False,
                                       initial_prompt=initial_prompt)
        words = []
        for s in segments:
            for w in (s.words or []):
                ws, we = max(a, w.start + pa), min(b, w.end + pa)
                if we > ws:
                    words.append({"start": round(ws, 3), "end": round(we, 3), "word": w.word})
        if not words:
            continue
        text = "".join(w["word"] for w in words).strip()
        seg = {"start": words[0]["start"], "end": words[-1]["end"], "text": text,
               "words": words, "gap": True}
        span = seg["end"] - seg["start"]
        if len(text.split()) >= substantive_words or span >= substantive_seconds:
            extra.append(seg)
        else:
            review.append(seg)
    return extra, review


# --------------------------------------------------------------------------
# Episode metadata lookup (RSS feed)
# --------------------------------------------------------------------------
def iter_feed_sources(project_root: Path, refresh: bool = False):
    """Yield (label, feed_xml) candidates in priority order.

    Lazy: each source is only loaded when the generator is advanced, so we
    avoid a network fetch when an earlier source already has the episode.

    Priority:
      1. output/cdspill-enriched.xml      (local enriched, guest tags, no network)
      2. GitHub Pages cdspill-enriched.xml (published enriched feed — current AND
                                            has guest tags, independent of the
                                            Podbean->Pages redirect being on)
      3. .cache/cdspill_feed.xml          (cached Podbean original, 24 h)
      4. Live fetch from Podbean          (raw; lacks guest tags when redirect off)

    The local enriched feed is preferred for its guest metadata and zero
    network cost, but it can lag behind for newly published episodes. The
    GitHub Pages copy is the published enriched feed: always current and
    always carries guest tags regardless of redirect state. Raw Podbean is a
    last resort because it lacks podcast:person guest tags when the redirect
    is off. Callers fall through to the next source when the episode isn't
    found rather than treating the first source as authoritative.
    """
    import urllib.request

    def _get(url):
        req = urllib.request.Request(url, headers={"User-Agent": "cdspill-transcribe"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8")

    # 1. Local enriched feed — richer metadata, no network needed
    enriched = project_root / "output" / "cdspill-enriched.xml"
    if enriched.exists():
        yield (
            f"local enriched feed ({enriched.relative_to(project_root)})",
            enriched.read_text(encoding="utf-8"),
        )

    # 2. Published enriched feed on GitHub Pages — current + guest tags,
    #    works even when the Podbean->Pages redirect is off.
    try:
        yield (
            "GitHub Pages enriched feed",
            _get("https://mrmamen.github.io/podcast-feed-updater/cdspill-enriched.xml"),
        )
    except Exception as e:
        print(f"  (GitHub Pages enriched feed unavailable: {e})")

    # 3. Cached Podbean original (skipped on --refresh-rss or if >24 h old)
    cache_dir = project_root / ".cache"
    cache_dir.mkdir(exist_ok=True)
    cached = cache_dir / "cdspill_feed.xml"
    if not refresh and cached.exists():
        age_hours = (time.time() - cached.stat().st_mtime) / 3600
        if age_hours < 24:
            yield (
                "cached Podbean feed (run enrich_cdspill.py for guest metadata)",
                cached.read_text(encoding="utf-8"),
            )

    # 4. Live fetch from Podbean (also refreshes the cache)
    content = _get("https://feed.podbean.com/cdspill/feed.xml")
    cached.write_text(content, encoding="utf-8")
    yield ("live Podbean feed", content)


def lookup_episode(project_root: Path, *, refresh: bool = False,
                   number: int | None = None, guid: str | None = None,
                   title_contains: str | None = None) -> dict | None:
    """Find episode metadata, trying each feed source until a match is found.

    A stale enriched feed no longer short-circuits the lookup: if the episode
    isn't present there, we fall through to the cached/live Podbean feed.
    """
    for label, feed_xml in iter_feed_sources(project_root, refresh=refresh):
        meta = find_episode(feed_xml, number=number, guid=guid,
                            title_contains=title_contains)
        if meta:
            print(f"Found episode in {label}")
            return meta
        print(f"Episode not in {label}, trying next source...")
    return None


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
# Cue splitting (to keep cues under max_cue_seconds)
# --------------------------------------------------------------------------
def split_cue_by_words(words: list, max_dur: float = 8.0,
                       max_chars: int = 120) -> list[tuple[float, float, str]]:
    """Split using word-level timestamps from Whisper.

    words: list of Word objects with .start, .end, .word
    Returns list of (start, end, text) — cues end at natural word boundaries,
    prefer ending after punctuation.
    """
    if not words:
        return []

    cues = []
    cur_start = words[0].start
    cur_words: list = []
    cur_chars = 0

    def flush(next_word_start: float | None):
        """Emit cue from cur_start to last word end (extended through short
        pauses if a next word follows soon). Returns new cur_start."""
        if not cur_words:
            return next_word_start
        text = "".join(w.word for w in cur_words).strip()
        last_end = cur_words[-1].end
        if next_word_start is not None:
            gap = next_word_start - last_end
            cue_end = next_word_start if gap < 1.0 else last_end
        else:
            cue_end = last_end
        # Safeguard against Whisper word-timestamp outliers (e.g. a single
        # word spanning a long musical passage): never exceed max_dur.
        if cue_end - cur_start > max_dur:
            cue_end = cur_start + max_dur
        cues.append((cur_start, cue_end, text))
        return next_word_start

    for i, w in enumerate(words):
        # Peek: would adding this word push cur over max_dur or max_chars?
        if cur_words:
            would_dur = w.end - cur_start
            would_chars = cur_chars + len(w.word)
            # Allow a small overshoot when the next word completes a
            # sentence, to avoid emitting orphan trailing cues like "and."
            stripped = w.word.strip()
            word_ends_sentence = bool(stripped) and stripped[-1] in ".!?"
            dur_limit = max_dur + (1.0 if word_ends_sentence else 0)
            if would_dur > dur_limit or would_chars > max_chars:
                # Forced split. Rather than cutting right here, back up to
                # the last punctuation inside the cue (if it leaves at least
                # 1 s on both sides) so the break lands on a natural pause.
                cut = None
                for j in range(len(cur_words) - 2, -1, -1):
                    wj = cur_words[j].word.strip()
                    if wj and wj[-1] in ".!?,;:" \
                            and cur_words[j].end - cur_start >= 1.0 \
                            and w.end - cur_words[j + 1].start >= 1.0:
                        cut = j
                        break
                if cut is not None:
                    carry = cur_words[cut + 1:]
                    cur_words = cur_words[:cut + 1]
                    cur_start = flush(carry[0].start)
                    cur_words = carry
                    cur_chars = sum(len(x.word) for x in carry)
                else:
                    cur_start = flush(w.start)
                    cur_words = []
                    cur_chars = 0

        cur_words.append(w)
        cur_chars += len(w.word)
        cur_dur = w.end - cur_start
        stripped = w.word.strip()
        ends_sentence = stripped and stripped[-1] in ".!?"
        ends_phrase = stripped and stripped[-1] in ",;:"

        # Preferred split: sentence end once the cue is >= 2 s (per
        # TRANSCRIPT_GUIDELINES), phrase boundary once it is nearly full.
        # Batched Whisper segments can be 30 s long, so without the
        # sentence rule cues would run across sentence boundaries.
        next_start = words[i + 1].start if i + 1 < len(words) else None
        if ends_sentence and cur_dur >= min(2.0, max_dur * 0.5):
            cur_start = flush(next_start)
            cur_words = []
            cur_chars = 0
        elif ends_phrase and cur_dur >= max_dur * 0.8:
            cur_start = flush(next_start)
            cur_words = []
            cur_chars = 0

    # Final flush
    if cur_words:
        flush(None)
    return cues


def split_long_cue(start: float, end: float, text: str,
                   max_dur: float = 8.0) -> list[tuple[float, float, str]]:
    """Split a cue into multiple shorter cues, preferring natural breaks.

    Returns list of (start, end, text) tuples. Time is allocated
    proportionally to character count of each chunk.
    """
    dur = end - start
    if dur <= max_dur:
        return [(start, end, text)]

    # Pick a splitter that produces enough chunks
    n_needed = int(dur / max_dur) + 1
    chunks = None
    for pattern in (
        r"(?<=[.!?])\s+",          # sentence boundary
        r"(?<=[.!?,;:])\s+",       # punctuation
        r"\s+(?:og|men|så|eller|fordi|for|når|hvis)\s+",  # conjunctions
        r"\s+",                     # whitespace fallback
    ):
        parts = re.split(pattern, text)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) >= n_needed:
            chunks = parts
            break
    if not chunks:
        chunks = [text]

    # Merge chunks into n_needed groups (roughly equal char count)
    total_chars = sum(len(c) for c in chunks)
    target = total_chars / n_needed
    groups, current, current_len = [], [], 0
    for c in chunks:
        current.append(c)
        current_len += len(c)
        if current_len >= target and len(groups) < n_needed - 1:
            groups.append(" ".join(current))
            current, current_len = [], 0
    if current:
        groups.append(" ".join(current))

    # Allocate time proportionally
    total_chars = sum(len(g) for g in groups)
    result = []
    cursor = start
    for g in groups[:-1]:
        g_dur = dur * len(g) / total_chars
        result.append((cursor, cursor + g_dur, g))
        cursor += g_dur
    result.append((cursor, end, groups[-1]))

    # Recurse if any sub-cue is still too long AND we made progress
    # (result has multiple chunks; if it's one big chunk, give up)
    final = []
    for (s, e, t) in result:
        if e - s > max_dur and len(result) > 1 and len(t.split()) > 2:
            final.extend(split_long_cue(s, e, t, max_dur))
        else:
            final.append((s, e, t))
    return final


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("audio", type=Path, nargs="?",
                        help="Input audio file. Omit to pick the episode's mix from "
                             "the local library using --episode-number.")
    parser.add_argument("-o", "--output", type=Path, required=True,
                        help="Output VTT path")
    parser.add_argument("--library", type=Path, default=DEFAULT_AUDIO_LIBRARY,
                        help=f"Episode folder root for audio lookup "
                             f"(default: $CDSPILL_LIBRARY or {DEFAULT_AUDIO_LIBRARY})")
    parser.add_argument("--no-diarization", action="store_true",
                        help="Skip pyannote diarization (faster, no <v> tags)")
    parser.add_argument("--speakers", type=int,
                        help="Exact number of speakers for diarization")
    parser.add_argument("--min-speakers", type=int,
                        help="Lower bound on speaker count (ignored with --speakers)")
    parser.add_argument("--max-speakers", type=int,
                        help="Upper bound on speaker count (ignored with --speakers)")
    parser.add_argument("--diarization-model", default=DEFAULT_DIARIZATION_MODEL,
                        help=f"pyannote pipeline (default: {DEFAULT_DIARIZATION_MODEL}; "
                             "legacy: pyannote/speaker-diarization-3.1)")
    parser.add_argument("--no-exclusive", action="store_true",
                        help="Use the raw overlapping diarization instead of the "
                             "pipeline's exclusive (one-speaker-at-a-time) output")
    parser.add_argument("--speaker-map", type=str,
                        help='Comma-separated mapping, e.g. "SPEAKER_00=Sigve,SPEAKER_01=Mamen"')
    parser.add_argument("--model", default="TheStigh/nb-whisper-large-ct2",
                        help="Whisper model name (HF repo or local CT2 dir)")
    parser.add_argument("--language", default="no")
    parser.add_argument("--sequential", action="store_true",
                        help="Use the classic sequential Whisper decoder instead of "
                             "BatchedInferencePipeline. Batched is the default: about "
                             "2x faster and, on a full episode, it kept ~10 min of "
                             "speech the sequential decoder skipped.")
    parser.add_argument("--batched", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--batch-size", type=int, default=8,
                        help="Batch size for batched decoding (default: 8)")
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
    parser.add_argument("--profile-threshold", type=float, default=PROFILE_THRESHOLD,
                        help=f"Minimum cosine similarity for a profile match "
                             f"(default: {PROFILE_THRESHOLD})")
    parser.add_argument("--line-width", type=int, default=42,
                        help="Wrap cue text at this many characters "
                             "(Apple Podcasts rejects unwrapped long lines). Default: 42")
    parser.add_argument("--max-cue-seconds", type=float, default=7.0,
                        help="Split cues longer than this many seconds. "
                             "Default: 7.0 (see transcripts/TRANSCRIPT_GUIDELINES.md)")
    parser.add_argument("--corrections", type=Path,
                        help="JSON with word/regex/phrase/post fixes to apply "
                             "(default: transcripts/corrections.json)")
    parser.add_argument("--vad-threshold", type=float, default=0.3,
                        help="Silero VAD speech threshold (0-1). Lower keeps "
                             "more quiet/music-bedded speech. Default: 0.3")
    parser.add_argument("--no-vad", action="store_true",
                        help="Disable VAD entirely (transcribe all audio; may "
                             "hallucinate text during silence/music)")
    parser.add_argument("--no-fill-gaps", action="store_true",
                        help="Skip the pass that finds stretches with speech Whisper "
                             "left untranscribed and re-transcribes them")
    parser.add_argument("--render-only", action="store_true",
                        help="Skip Whisper and pyannote; re-render the VTT from the raw "
                             "results cached by the previous run with the same -o "
                             "(.cache/raw/<name>.json). For tuning cue splitting, "
                             "corrections and speaker maps without the GPU.")
    parser.add_argument("--env", type=Path,
                        help="Path to .env file (default: project root)")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent

    hf_token = load_hf_token(args.env)

    raw_path = project_root / ".cache" / "raw" / (args.output.stem + ".json")
    if args.render_only:
        if not raw_path.exists():
            sys.stderr.write(f"No cached raw results at {raw_path}; run without "
                             f"--render-only first.\n")
            return 1
        return render_from_raw(args, raw_path)

    if args.audio is None:
        if not args.episode_number:
            sys.stderr.write("Give an audio file, or --episode-number to find it "
                             "in the local library.\n")
            return 1
        try:
            args.audio = find_episode_audio(args.episode_number, args.library)
        except FileNotFoundError as e:
            sys.stderr.write(f"{e}\n")
            return 1
    if not args.audio.exists():
        sys.stderr.write(f"Audio not found: {args.audio}\n")
        return 1

    # Parse speaker map
    speaker_map: dict[str, str] = {}
    if args.speaker_map:
        for pair in args.speaker_map.split(","):
            k, _, v = pair.partition("=")
            speaker_map[k.strip()] = v.strip()

    corrections = load_corrections(args.corrections)

    # Episode metadata lookup (if requested)
    initial_prompt = args.initial_prompt
    meta = None
    if args.episode_number or args.episode_guid or args.episode_title:
        meta = lookup_episode(project_root, refresh=args.refresh_rss,
                              number=args.episode_number,
                              guid=args.episode_guid,
                              title_contains=args.episode_title)
        if not meta:
            sys.stderr.write("Episode not found in any RSS source.\n")
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
    wav = load_audio(args.audio)
    print(f"  {len(wav)/16000/60:.1f} min decoded in {time.time()-t0:.1f}s")

    segs, duration, model = transcribe(
        wav, model_name=args.model, language=args.language,
        initial_prompt=initial_prompt,
        vad_threshold=None if args.no_vad else args.vad_threshold,
        batched=not args.sequential, batch_size=args.batch_size,
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
            pipeline = load_diarization_pipeline(hf_token, args.diarization_model)
            diar_segments = run_diarization(
                pipeline, wav, num_speakers=args.speakers,
                min_speakers=args.min_speakers, max_speakers=args.max_speakers,
                exclusive=not args.no_exclusive,
            )

    # Auto-identify known speakers from profiles
    if diar_segments and args.profiles and not speaker_map:
        profile_map = match_profiles(
            diar_segments, wav, pipeline, args.profiles,
            threshold=args.profile_threshold,
        )
        # Merge: profile matches for known hosts, guest names for the rest
        guest_names = [p for p in (meta.get("people", []) if meta else [])
                       if p not in profile_map.values()]
        unmatched = sorted(set(s["speaker"] for s in diar_segments) - set(profile_map))
        speaker_map.update(profile_map)
        # Assign guest names to unmatched speakers by talk-time (most → first guest)
        if guest_names and unmatched:
            totals = speaker_totals([s for s in diar_segments if s["speaker"] in unmatched])
            for spk in sorted(totals, key=lambda x: -totals[x]):
                if guest_names:
                    speaker_map[spk] = guest_names.pop(0)
                    print(f"  {spk} → {speaker_map[spk]} (guest from metadata)")

    # Fill gaps Whisper skipped (see fill_gaps); short interjections are
    # only listed, in line with the subtitle style in TRANSCRIPT_GUIDELINES.
    gap_review: list[dict] = []
    if not args.no_fill_gaps:
        extra, review = fill_gaps(model, wav, segs, language=args.language,
                                  initial_prompt=initial_prompt)
        for r in review:
            spk = speaker_for_range(diar_segments, r["start"], r["end"]) if diar_segments else None
            r["speaker"] = speaker_map.get(spk, spk) if spk else None
        gap_review = review
        if extra:
            segs = sorted(segs + [_Seg(s) for s in extra], key=lambda s: s.start)
            print(f"  inserted {len(extra)} skipped passages "
                  f"({sum(s['end'] - s['start'] for s in extra):.0f}s):")
            for s in extra:
                print(f"    {format_ts(s['start'])}  {s['text'][:80]}")
        print_gap_review(gap_review)

    # Cache raw results so --render-only can re-render without the GPU
    raw = {
        "audio": str(args.audio),
        "duration": duration,
        "segments": [
            {"start": s.start, "end": s.end, "text": s.text,
             "words": [{"start": w.start, "end": w.end, "word": w.word}
                       for w in (getattr(s, "words", None) or [])],
             "gap": bool(getattr(s, "gap", False))}
            for s in segs
        ],
        "diarization": diar_segments,
        "speaker_map": speaker_map,
        "gap_review": gap_review,
    }
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    print(f"  raw results cached in {raw_path.relative_to(project_root)}")

    render_vtt(args, segs, diar_segments, speaker_map, corrections)

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


class _Word:
    __slots__ = ("start", "end", "word")

    def __init__(self, d):
        self.start, self.end, self.word = d["start"], d["end"], d["word"]


class _Seg:
    __slots__ = ("start", "end", "text", "words", "gap")

    def __init__(self, d):
        self.start, self.end, self.text = d["start"], d["end"], d["text"]
        self.words = [_Word(w) for w in d.get("words", [])]
        self.gap = bool(d.get("gap", False))


def print_gap_review(review: list[dict]) -> None:
    if not review:
        return
    print(f"  {len(review)} short interjection(s) in gaps, not inserted "
          f"(add by hand if they matter):")
    for r in review:
        who = f"{r['speaker']}: " if r.get("speaker") else ""
        print(f"    {format_ts(r['start'])}  {who}{r['text']}")


def render_from_raw(args, raw_path: Path) -> int:
    """--render-only: rebuild the VTT from cached Whisper/pyannote output."""
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    segs = [_Seg(s) for s in raw["segments"]]
    diar_segments = raw.get("diarization")
    speaker_map = dict(raw.get("speaker_map") or {})
    if args.speaker_map:
        for pair in args.speaker_map.split(","):
            k, _, v = pair.partition("=")
            speaker_map[k.strip()] = v.strip()
    corrections = load_corrections(args.corrections)
    print(f"Re-rendering from {raw_path} ({len(segs)} segments, "
          f"{len(diar_segments or [])} diarization turns)")
    render_vtt(args, segs, diar_segments, speaker_map, corrections)
    print_gap_review(raw.get("gap_review") or [])
    print(f"  {args.output}")
    return 0


def render_vtt(args, segs, diar_segments, speaker_map, corrections) -> None:
    """Split segments into cues, tag speakers, apply corrections, write VTT."""
    import textwrap
    print(f"\nWriting {args.output}...")
    lines = ["WEBVTT", ""]
    split_count = 0
    word_split = 0
    all_cues = []

    def speaker_at(start: float, end: float) -> str | None:
        if not diar_segments:
            return None
        spk = speaker_for_range(diar_segments, start, end)
        return speaker_map.get(spk, spk) if spk else None

    for seg in segs:
        # Prefer word-level splitting when word timestamps are available
        if getattr(seg, "words", None):
            sub_cues = split_cue_by_words(seg.words,
                                           max_dur=args.max_cue_seconds,
                                           max_chars=args.line_width * 3)
            sub_cues = [(s, e, apply_corrections(t, corrections))
                         for (s, e, t) in sub_cues]
            word_split += 1 if len(sub_cues) > 1 else 0
        else:
            text = apply_corrections(seg.text.strip(), corrections)
            sub_cues = split_long_cue(seg.start, seg.end, text,
                                       max_dur=args.max_cue_seconds)
        if len(sub_cues) > 1:
            split_count += len(sub_cues) - 1

        # Speaker is decided per cue, not per Whisper segment: a segment can
        # span a speaker change (especially in batched mode).
        for (cue_start, cue_end, cue_text) in sub_cues:
            all_cues.append([cue_start, cue_end, cue_text,
                             speaker_at(cue_start, cue_end)])

    for (cue_start, cue_end, cue_text, speaker) in all_cues:
        wrapped = textwrap.wrap(cue_text, width=args.line_width,
                                break_long_words=False,
                                break_on_hyphens=False) or [""]
        if speaker:
            wrapped[0] = f"<v {speaker}>{wrapped[0]}"
        lines.append(f"{format_ts(cue_start)} --> {format_ts(cue_end)}")
        lines.extend(wrapped)
        lines.append("")

    if split_count:
        print(f"  Split {split_count} cues ({word_split} via word-level timing)")

    args.output.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
