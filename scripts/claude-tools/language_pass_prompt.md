You are doing the language pass on one chunk of a Norwegian podcast transcript (cd SPILL, episode {EPISODE}; speakers: {SPEAKERS}). Work directly on the files; do not ask questions.

Files (absolute paths):
- Chunk to edit IN PLACE: {CHUNK_VTT}
- Reference (read only): {CHUNK_REF} — the transcript of each speaker's own microphone track, mapped into mix time, plus the last cues of the previous chunk and the first cues of the next one as context. The reference's speaker attribution is ground truth. Its text is the best source for words the mix transcript garbled or missed, but it also contains chatter that was cut from the mix or drowned by another speaker, so do not add everything it has.
- Style rules you must follow: {GUIDELINES} (read it first, especially sections 2, 3 and 4).
- Permanent word list already applied: {CORRECTIONS} (do not edit it).

What to do, cue by cue:
1. Fix wrong words using the reference. Proper names and terms in canonical spelling: {TERMS}. English words spoken in English stay English. Keep the speakers' own Norwegian words and dialect; condense, never rewrite into prose.
2. Drop fillers (eh, ehm, altså as a tic), false starts and empty backchannel ("Ja.", "Mhm.") standing alone. A cue that becomes empty: delete the whole cue (timestamp line included). When two people overlap, keep the voice that carries content.
3. Speaker tags: the `<v Name>` tag on each cue comes from the solo tracks and is reliable for the cue as a whole. Do not change a tag based on who you think would say it. Act only when the reference shows the cue's words belong to two speakers: put each speaker's words on its own line with its own tag, e.g.
   <v Mamen>Så tenkte jeg det.
   <v Sigve>Det står mitt hjerte veldig nært.
   A later automatic pass splits or merges these. You may retag a whole cue only when the reference shows every word in it is another speaker's. If you truly cannot tell, use `<v ?>`. Allowed tags: {TAGS}.
   {CLIPS}
4. The first and last cues of the chunk may continue a sentence from the context cues in the reference. Edit them so the sentence reads correctly across the boundary; do not repeat text that the neighbouring chunk already has.
5. Do not change any timestamp, do not add new cues, do not reorder. Text lines only, plus deleting whole cues. Do not move words from one cue into another, not even to complete a sentence: the timestamps belong to the words, and a moved phrase is shown seconds before or after it is spoken. A sentence may run over two cues. Lines wrap automatically later; you may write a cue's text on one line. Use the single character … for trailing off, never "...".
6. A cue whose text you cannot make sense of from any source: leave it as is and list it in the report.

When done:
- Overwrite {CHUNK_VTT} with the edited chunk. Keep the "WEBVTT" header and blank-line separated cues, UTF-8, LF.
- Write {CHUNK_REPORT}: at most 15 short lines, one item per line, grouped under "Uncertain", "Split cues", "Retagged", "Deleted cues (count)", "Notes". Timestamps as hh:mm:ss as they appear in the file. No prose about your process.
Do not touch any other file. Reply with the path of the report only.
