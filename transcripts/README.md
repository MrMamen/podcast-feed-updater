# Transcripts

Publiserbare VTT-transcripts for podcast-episoder, og verktøy for å lage nye.

## Innhold

- `*.vtt` — publiserbare transcripts (én per episode)
- `corrections.json` — permanent rettelsesordliste (egennavn, terminologi) som gjelder alle episoder
- `<episode>.config.json` — episode-spesifikk config (arver fra `corrections.json`)

## Primær workflow: `scripts/transcribe.py`

For å transkribere en ny episode fra audio:

```bash
uv run python scripts/transcribe.py \
  "/path/to/Episode.mp3" \
  -o transcripts/Episode.vtt \
  --episode-number 130 \
  --speakers 3
```

Scriptet gjør:

1. Dekoder lyd via PyAV (ffmpeg-bundled)
2. Henter episode-metadata fra RSS-feeden (cached lokalt i `.cache/`)
3. Bygger automatisk `initial_prompt` fra episodetittel, gjesteliste, kapitler
4. Transkriberer med **NB-Whisper large** (norsk-optimert)
5. Kjører **pyannote speaker diarization** parallelt
6. Merger: hver cue får `<v SPEAKER_XX>` basert på tidsoverlapp
7. Applikerer `corrections.json` (navn, terminologi)
8. Skriver VTT og printer speaker-preview så du kan identifisere talere

**Ytelse:** ~8x sanntid på GPU (en 90 min episode tar ~12 min).

## Typiske CLI-flagg

| Flagg | Beskrivelse |
|---|---|
| `--episode-number N` | Auto-henter metadata fra RSS for episode N |
| `--episode-title "Stunt"` | Alternativt: match tittel-fragment |
| `--episode-guid "abc..."` | Alternativt: match GUID-fragment |
| `--speakers N` | Hint til diarization om antall talere |
| `--speaker-map "SPEAKER_00=Sigve,..."` | Map talere til navn direkte |
| `--no-diarization` | Hopp over pyannote (raskere, ingen `<v>`-tags) |
| `--initial-prompt "..."` | Overstyr auto-prompt med egne termer |
| `--refresh-rss` | Tving ny nedlasting av RSS (ellers brukes 24h cache) |
| `--corrections FILE` | Bruk annen rettelsesordliste |

## Etter transkripsjon: identifiser talere

Scriptet printer 3 eksempel-setninger per taler ved slutt:

```
--- Speaker preview (first 3 utterances each) ---
  SPEAKER_00 [00:00:48]: Jeg heter Sigve, og dette er CD-spill.
  SPEAKER_01 [00:01:36]: Jeg ble sendt hjem fra skolen, til rektor...
  SPEAKER_02 [00:02:35]: Næfjord er jo fordi det er der jeg er fra.
```

Kjør så på nytt med `--speaker-map` (audio re-dekodes ikke hvis samme kjøring),
eller bare gjør en tekst-replace i VTT-filen.

## Prerequisites

- **NVIDIA GPU** (CUDA 12+). CPU-fallback er veldig tregt.
- **HF_TOKEN** i `.env`-fila (for pyannote). Godta lisens på:
  - https://huggingface.co/pyannote/speaker-diarization-3.1
  - https://huggingface.co/pyannote/segmentation-3.0
  - https://huggingface.co/pyannote/speaker-diarization-community-1
- Uten HF_TOKEN: bruk `--no-diarization` flagg

## corrections.json — hva som hører hjemme der

Legg **permanente** korrigeringer her (ord/navn som går igjen på tvers av episoder):

- Verter: Mr. Mamen, Sigve variasjoner
- Faste gjester: Aleksikon, Spruceman, Dr. Bobledrage osv.
- Terminologi: CD-spillytter, pek-og-klikk, CRT-skjerm
- Norske vanlige ord: hodene, berlinerbolle, marihuana osv.

For **episode-spesifikke** rettelser (ett bestemt spill/gjest som kun nevnes
én gang), rediger VTT-en direkte etter generering, eller bruk en
`<episode>.config.json` hvis det er gjentakende for flere relaterte episoder
(f.eks. påskelabyrint-serien).

## Publisering

Etter du har en ferdig `.vtt`:

1. Last opp til din hosting-provider (podbean el.l.)
2. Legg til `<podcast:transcript url="..." type="text/vtt" language="nb"/>` i RSS-feeden for episoden
3. Apple Podcasts, Podverse, Fountain og andre podcasting-2.0-spillere vil vise transkripsjonen din fremfor auto-genererte

## Legacy: `scripts/normalize_transcript.py`

Dette er det gamle scriptet som normaliserer YouTube karaoke-VTT til
setnings-baserte kuer. Fortsatt nyttig hvis du har eksisterende
YouTube-transcripts å konvertere, men `transcribe.py` er primærveien for
nye episoder.
