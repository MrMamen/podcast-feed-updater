# Transcript Guidelines

These are the conventions used for cd SPILL podcast transcripts. They
prioritize **reading experience** and **faithfulness to the actual
episode** over conformance to any single distribution platform's rules.

## Principles

1. **Faithfulness before polish** — preserve what was actually said,
   including hesitations, dialect, and speaker voice.
2. **Readability before perfection** — split cues at natural pauses, not
   arbitrary durations.
3. **Silence is data** — leave gaps when the audio is silent or purely
   musical; do not force continuous timing.
4. **Apple is one app** — many podcast clients read `podcast:transcript`.
   Do not sacrifice reader value for any single platform's opaque
   validation rules.

---

## 1. Timing

### Cue duration

| | Target | Allowed |
|---|---|---|
| Minimum duration | ≥ 1.0s | 0.3s absolute floor |
| Maximum duration | ≤ 5.0s (ideal) | 7.0s hard ceiling |
| Typical | 2–5s | |

If a single word spans > 5s because of surrounding pauses, **extend the
cue to cover the pause** rather than flashing the word briefly followed
by dead air.

### Gaps between cues

- **Short pause (< 1s)** between adjacent words in the same thought →
  let the previous cue extend through the pause (implicit back-to-back).
- **Longer silence (≥ 1s)** → leave a gap. The viewer sees no subtitle
  during the silence. This is honest.
- **Music or sound effect breaks** → gap, no `[Music]` marker.
- **Topic transitions / scene breaks** → gap.

Never force 100% back-to-back timing. Silence is meaningful.

## 2. Text content

### What to preserve

- Speaker voice: dialect, colloquialisms, register.
- Meaningful hesitations: "eh", "hmm" when used as thinking markers.
- Self-corrections and false starts — they're part of natural speech.
- Code-switching: English words or phrases spoken in the episode stay
  in English (Norwegian speech stays Norwegian).
- Ellipses (…) to indicate trailing off or significant pauses.

### What to fix

- **ASR hallucinations**: stray CJK characters, random symbols from
  silent passages.
- **Non-speech markers**: `[Music]`, `[Laughter]` — remove; silence or
  laughter is not speech.
- **Systematic ASR errors**: e.g. nb-whisper consistently writes "òg"
  for "og" — fix via corrections.json.
- **Clear name/term misspellings**: guest names, game titles, technical
  terms in their canonical form.

### What NOT to do

- Do not "polish" text into literary prose. Readers should hear the
  speakers.
- Do not remove filler words wholesale (eh, ehm, øh) — they carry
  rhythm and character.
- Do not change meaning or word choice for style.

## 3. Cue segmentation

### Where to split

Prefer splits at these boundaries, in priority order:

1. **Sentence end** (`.`, `!`, `?`) — always prefer this when cue
   duration ≥ 2s.
2. **Phrase boundary** (`,`, `;`, `:`) — acceptable when approaching
   the max duration.
3. **Conjunction** (og, men, så, eller, fordi, for, når, hvis) — a
   fallback when no punctuation is available.
4. **Any whitespace** — last resort, only if a cue would otherwise
   exceed 7s.

Use word-level timestamps (`word_timestamps=True` in faster-whisper) so
splits fall on actual word boundaries, not estimated positions.

## 4. Formatting

### Line length and layout

- **Max characters per line**: 42
- **Max lines per cue**: 2
- Break at word boundaries only; never split mid-word or mid-hyphen.

### Speaker labels

Use `<v Name>` voice tags when a speaker is identified.

- Apply the tag to **every cue** from that speaker (not only on
  speaker changes). This aids screen readers and full-text search.
- Use the same form throughout the episode (first + last name, or
  short form if consistently used in-show).
- Unknown/unmatched speakers: no tag (do not invent names).

### Header

Just the `WEBVTT` header followed by a blank line. No `Kind: captions`
or `Language:` metadata lines — they are optional in the spec and some
stricter parsers prefer them absent.

```
WEBVTT

00:00:00.500 --> 00:00:03.200
<v Sigve>Velkommen tilbake til cd SPILL.
```

## 5. Pipeline defaults

These match the guidelines above:

- `--line-width 42`
- `--max-cue-seconds 7.0`
- `--profiles transcripts/speaker_profiles.npy` (host auto-ID)
- `--corrections transcripts/corrections.json` (shared ASR fixes)

## 6. Tools

### `scripts/transcribe.py`

Main pipeline. Runs nb-whisper ASR, pyannote diarisation, and profile
matching. Produces a tagged VTT.

**Running it for a newly published episode:**

```bash
uv run python scripts/transcribe.py "<path/to/Mix.mp3>" \
  -o transcripts/<Name>.vtt \
  --speakers <count> \
  --profiles transcripts/speaker_profiles.npy \
  --corrections transcripts/corrections.json \
  --episode-number <N>
```

| Flag | Purpose |
|---|---|
| `<audio>` (positional) | Path to the finished mix MP3 |
| `-o` | Output VTT path (required) |
| `--speakers N` | Speaker count for diarisation — count hosts + guests, **not** game audio |
| `--profiles` | Voice profiles for auto-tagging known people |
| `--corrections` | Shared ASR fixes applied to every episode |
| `--episode-number N` | Looks up title/guests/prompt in the RSS feed |

Variants:
- **Solo track (single speaker):** add `--no-diarization`, drop
  `--speakers`/`--profiles`.
- **Identify by title:** `--episode-title "Magic Carpet"` instead of
  `--episode-number`.
- **Force a fresh feed:** `--refresh-rss` skips the 24 h cache. Rarely
  needed — see feed sources below.

After transcribing: language pass as usual, and set the guest's name on
the unmatched cluster manually (guests rarely have a profile). Use
`scripts/add_speakers.py` to re-tag later if you build a guest profile.

**Episode metadata feed sources** (tried in order, falling through when
the episode isn't found — so a stale local feed no longer blocks a newly
published episode):

1. `output/cdspill-enriched.xml` — local enriched feed (guest tags, no
   network), but can lag behind for brand-new episodes
2. `https://mrmamen.github.io/podcast-feed-updater/cdspill-enriched.xml`
   — published enriched feed on GitHub Pages: always current AND carries
   guest tags, **regardless of whether the Podbean→Pages redirect is on**
3. `.cache/cdspill_feed.xml` — cached raw Podbean (24 h)
4. Live Podbean fetch — raw feed; lacks guest tags when redirect is off

Because of source 2, transcribe finds newly published episodes with
correct guest metadata even if you forgot to flip the redirect or
regenerate the local enriched feed.

### `scripts/add_speakers.py`

Re-tag speakers on an existing VTT *without re-transcribing*. Useful
when the profile set has been updated, or when mix VTT has wrong
speaker tags but text is correct. Keeps hand-corrections intact —
only the `<v Speaker>` tag changes.

```
uv run python scripts/add_speakers.py <audio> <vtt> <num_speakers>
```

### `scripts/build_speaker_profiles.py`

Build profiles from previously-labelled VTTs (extracts the long,
clean segments and averages embeddings).

### `scripts/build_profiles_clean.py`

Build profiles from clean multitrack recordings (one speaker per
file). Higher-quality alternative when you have isolated tracks for
each host/guest. Takes a JSON config mapping speaker name → list of
audio files.

## 7. Multitrack / solo-track workflow

For most episodes the mix is enough — profile matching is robust
(typical sim 0.85-0.95) and the mix captures primary dialogue fine.

Consider running solo tracks (one per speaker) through the pipeline
separately when:

1. **Heavy cross-talk / panel format** — multiple speakers competing
   simultaneously, where the mix loses one speaker's words
2. **Weak profile match** (sim < 0.75) — solo track can confirm or
   correct the tagging
3. **New guest without a profile** — solo track lets you build a
   profile while you transcribe
4. **Mic balance issues** — one speaker much quieter in the mix

For solo tracks, run with `--no-diarization` (single speaker, no
diarisation needed). The pipeline still applies VAD filtering so
silent gaps don't hallucinate. Solo VTTs are best used as a
*reference* during language pass, not auto-merged — they translate
English passages to Norwegian and don't have speaker tags.

## 8. Language attribute in the RSS feed

The enrichment pipeline (`enrich_cdspill.py`) adds `language="no"` to
`<podcast:transcript>` tags for all episodes, with a per-GUID override
for English content (Martin Alper interview).

---

## Appendix: known rejection patterns

The Apple Podcasts Connect validator rejects almost all ASR-generated
transcripts for Norwegian content, regardless of format. Empirically,
the only variants that pass are manuscript-derived transcripts (where
the text was written by a human and aligned to YouTube word timing).

We do not attempt to satisfy Apple's opaque validator. Transcripts
remain useful in Overcast, Podverse, Fountain, website search, and AI
summarization — Apple is one app among many.
