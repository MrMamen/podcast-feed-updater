You are doing the language pass on one chunk of a Norwegian podcast transcript (cd SPILL, episode {EPISODE}; speakers: {SPEAKERS}). Work directly on the files; do not ask questions.

Files (absolute paths):
- Chunk to edit IN PLACE: {CHUNK_VTT}
- Context (read only): {CHUNK_REF} — the last cues of the previous chunk and the first cues of the next one.
{REFERENCE}- Style rules you must follow: {GUIDELINES} (read it first, especially sections 2, 3 and 4).
- Permanent word list already applied: {CORRECTIONS} (do not edit it).

How the chunk was made: each speaker's own microphone track was placed in mix time exactly as in the edited episode and transcribed on its own with NB-Whisper. So:
- The `<v Name>` tag on every cue is certain. Never change a tag and never move text from one speaker to another. A cue with two `<v>` lines is two people talking at the same time; keep both lines or delete one as in step 3.
- The words are from a clean single voice and usually right. NB-Whisper sometimes mishears names and game terms, and it TRANSLATES English phrases into Norwegian ("I'm the guy" comes out as "Jeg er fyren").

What to do, cue by cue:
1. Fix misheard words, names and terms. Canonical spellings: {TERMS}. When it is clear the speaker said something in English, write it in English.
2. Subtitle style: drop fillers (eh, ehm, altså as a tic), stutters, false starts and repeated words. Keep the speaker's own words and dialect. Condense only clumsy repetition; keep every piece of content, including numbers, names and the end of a sentence.
3. Overlaps: a short backchannel cue or line ("Ja.", "Mhm.", "Ja, ja.", laughter, a lone "Nei") that overlaps another speaker's content: delete it. Keep short replies that answer something or carry meaning ("Enig.", "Nei, aldri.").
4. Allowed tags: {TAGS}. {CLIPS}
5. Do not change any timestamp, do not add cues, do not reorder, do not move words from one cue into another (the timestamps belong to the words). A cue that becomes empty: delete it, timestamp line included. Text lines only; you may write a cue's text on one line. Use … for trailing off, never "...".
6. Never add text that is not in the chunk, not even from the reference. The chunk is what the microphones recorded in the edited episode; the reference may contain speech that was cut. If the reference has a sentence the chunk has nowhere, list it in the report.

When done:
- Overwrite {CHUNK_VTT} with the edited chunk. Keep the "WEBVTT" header and blank-line separated cues, UTF-8, LF.
- Write {CHUNK_REPORT}: at most 12 short lines, grouped under "Uncertain", "Only in reference", "Deleted cues (count)", "Notes". Timestamps hh:mm:ss as in the file. No prose about your process.
Do not touch any other file. Reply with the path of the report only.
