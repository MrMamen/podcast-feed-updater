# Transcript Guidelines

These are the conventions used for cd SPILL podcast transcripts. They
prioritize **reading experience** and **what the speakers meant** over
verbatim reproduction and over any single distribution platform's rules.

## Principles

1. **Subtitles, not a court record** — the transcript is read, not
   audited. Keep the speakers' own words and meaning, drop what only
   adds noise (fillers, empty backchannel, one of two overlapping voices).
   nb-whisper is trained on subtitles and already leans this way.
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
| Maximum duration | ≤ 5.0s (ideal) | 7.0s in the pipeline; up to ~8s by hand when the only alternative is an unnatural split |
| Typical | 2–5s | |

If a single word spans > 5s because of surrounding pauses, **extend the
cue to cover the pause** rather than flashing the word briefly followed
by dead air.

### Reading time

A cue must stay on screen long enough to read: at least 1 s, and about
**17 characters per second** of text (a full 42-character line needs
~2.5 s). When a cue is shorter than that and there is silence after it,
extend its end into the silence, up to the next cue's start or the 7 s
ceiling. Back-to-back cues cannot be helped this way; if one is far too
short, merge it with its neighbour instead. The pipeline applies this
rule automatically when rendering.

**Cue ends are padded 0.5 s into a following pause.** Whisper's word
end times land a few hundred milliseconds before the speaker has finished
the word, so a cue that is followed by silence would otherwise cut off
early (measured on episode 87: hand corrections extended such cues by
0.3–0.8 s). The pipeline and `--polish` push every end up to 0.5 s into
the pause, never past the next cue or the 7 s ceiling (`--tail-pad 0`
turns it off).

**25 characters per second is the hard ceiling.** Above that the text is
unreadable; shorten it or merge the cue with a neighbour. `--polish`
lists cues over the ceiling (counting all characters, spaces included,
tags excluded, like Subtitle Edit's "count all characters").

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

- Speaker voice: dialect, colloquialisms, register. Condense, don't
  rewrite.
- Code-switching: English words or phrases spoken in the episode stay
  in English (Norwegian speech stays Norwegian). Game and film clips
  are transcribed in their original language and tagged with the
  character's name (`<v Picard>`).
- Ellipses to indicate trailing off, or a pause in the middle of a
  sentence that continues in the next cue (on the end of the first cue
  only, never on the start of the next). Use the single character «…»,
  not three periods; `corrections.json` turns "..." into «…».
- A sentence that simply continues in the next cue gets no marker at
  all: no ellipsis, no dash.

### What to drop or condense

- **Filler words** (eh, ehm, øh, "altså" as a tic) — omit unless they
  carry meaning in context.
- **Empty backchannel** ("Ja.", "Mhm.", "Og …") standing on its own —
  omit. The gap-filling pass in `transcribe.py` lists these instead of
  inserting them, for exactly this reason.
- **Long or clumsy phrasing** — shorten to what was meant, keeping the
  speaker's own words as far as possible.
- **False starts and self-corrections** — keep the corrected version
  only, unless the slip itself is the point.
- **Overlapping speech** — keep the voice that carries the content,
  which is usually exactly one of them. Do not try to render both.

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

- Do not "polish" text into literary prose. Condensing is removal, not
  rephrasing; readers should still hear the speakers.
- Do not change meaning or word choice for style.
- Do not invent text for passages you cannot hear. Leave a gap.

## 3. Cue segmentation

### One sentence per cue, condense before you split

A sentence stays in one cue when it fits. When it does not, **shorten
the text first**: a spoken sentence too long for 7 s is almost always
too long as text too, and after dropping fillers and detours it often
fits. Only then split, and only at a clause boundary. Never split
mid-phrase, and do not accept a split that reads worse than a cue of
8 s.

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
- **Max lines per cue**: 2 (so at most 84 characters of text; `--polish`
  lists cues that wrap to three lines, shorten those)
- Break at word boundaries only; never split mid-word or mid-hyphen.

### Speaker labels

Use `<v Name>` voice tags when a speaker is identified.

- Apply the tag to **every cue** from that speaker (not only on
  speaker changes). This aids screen readers and full-text search.
- Hosts and guests by first name: `<v Mamen>`, `<v Sigve>`,
  `<v Jostein>`. The pipeline renders this from the full profile name
  automatically; exceptions (two guests sharing a first name, a
  preferred nickname) go under `"speaker_names"` in
  `transcripts/corrections.json`.
- Voices in game or film clips by character name: `<v Picard>`,
  `<v Data>`, or a role when unnamed: `<v Garidiansk kaptein>`. These
  are set by hand.
- Unknown/unmatched speakers: no tag (do not invent names).

### Two speakers in one cue

A quick exchange or overlap often gives two parts that are each too
short to stand alone. Then keep them in **one cue with two tags**, each
speaker on its own line:

```
00:04:12.480 --> 00:04:15.200
<v Mamen>De husker jeg var morsomme.
<v Jostein>Ja, de er kule.
```

Rule of thumb: split into two cues only when **both** parts would last
at least 1.5 s and hold at least three words. When only one part is too
short and the neighbouring cue on that side is the same speaker, merge
the short part into that neighbour instead (if the result stays under
7 s and two lines) and let the other part stand alone. `transcribe.py
--polish` applies exactly these rules to cues you have marked with a
second `<v>` line, using word timestamps from the raw cache, and leaves
the rest as two-speaker cues. When one voice carries the content and the other is
just noise, keep only the one that matters (see section 2).

### Header and file format

Just the `WEBVTT` header followed by a blank line. No `Kind: captions`
or `Language:` metadata lines — they are optional in the spec and some
stricter parsers prefer them absent. UTF-8 without BOM, LF line endings.
`&`, `<` and `>` in cue text are written as `&amp;`, `&lt;` and `&gt;`
as the spec requires; the pipeline escapes on write and decodes on read,
and tolerates a BOM, CRLF and entities from other editors.

```
WEBVTT

00:00:00.500 --> 00:00:03.200
<v Sigve>Velkommen tilbake til cd SPILL.
```

## 4b. Editing in Subtitle Edit

Subtitle Edit keeps `<v>` tags intact and is fine for timing work. Use a
custom rules profile that matches these guidelines, so its warnings mean
something:

| Setting | Value |
|---|---|
| Single line max length | 42 |
| Optimal chars/sec | 17 |
| Max chars/sec | 25 |
| Max words/min | 400 (never triggers; chars/sec is the real check) |
| Min duration | 1000 ms |
| Max duration | 8000 ms |
| Min gap | 0 ms (cues are back-to-back) |
| Max number of lines | 2 |
| Unbreak subtitles shorter than | 42 |
| Dialog style | leave as is; do not use the dialog feature, tag each speaker with `<v>` on its own line |
| Continuation style | None, ellipsis for pauses (trailing only) |
| Cps/line-length | Count all characters |
| Encoding | UTF-8 without BOM |
| Line endings | LF if the option exists; `--polish` normalises otherwise |

After saving, run `transcribe.py -o <file> --polish` and read its report
(cues over 7 s, overlaps, three-line cues, cues over 25 cps).

## 5. Pipeline defaults

These match the guidelines above:

- `--line-width 42`
- `--max-cue-seconds 7.0`
- `--profiles transcripts/speaker_profiles.npy` (host auto-ID)
- `--corrections transcripts/corrections.json` (shared ASR fixes)

## 6. Tools

The tools are documented in `transcripts/README.md`; this section only
says which rule each one enforces.

- `scripts/transcribe.py` renders cues from word timestamps (sections 1
  and 3), applies `corrections.json`, pads cue ends 0.5 s into the pause,
  extends cues that are too short to read, and fills stretches Whisper
  skipped (passages of 4+ words or 2.5+ s are inserted, shorter
  interjections only listed, section 2).
- `scripts/align_solo.py` takes speaker tags and missed speech from the
  solo tracks through the Reaper project, and transcribes game and film
  clips from the clean files in their own language (section 2,
  code-switching). Use it for every episode that has the `.rpp` and one
  recording per microphone; pyannote is only for episodes without them.
- `transcribe.py --polish` is the pass to run after every round of hand
  editing: it splits or merges cues marked with a second `<v>` line by
  the rules in section 4, applies the word list, re-wraps at 42
  characters, and lists cues over 7 s, overlaps, three-line cues and cues
  over 25 characters per second. No GPU.
- `scripts/add_speakers.py` re-tags an existing VTT with pyannote and the
  profiles without touching the text; `build_speaker_profiles.py` and
  `build_profiles_clean.py` build those profiles.

## 7. Solo tracks

Solo tracks are the authority on who said what. The mix transcript stays
the text (nb-whisper condenses it the way section 2 asks), the solo words
decide the speaker of each cue and fill what the mix skipped, and the
Reaper project is the map between the two. Cross-talk therefore needs no
special handling in the pipeline; the language pass keeps the voice that
carries the content, as section 2 says.

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
