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

## 6. Language attribute in the RSS feed

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
