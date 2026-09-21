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
  -o transcripts/Episode.vtt \
  --episode-number 130 \
  --profiles transcripts/speaker_profiles.npy
```

Uten lydfil som argument finner scriptet mixen selv i det lokale
episodebiblioteket (`T:\MrMamen\CD SPILL\`, altså `/mnt/t/MrMamen/CD SPILL`
fra WSL; overstyr med `--library` eller `CDSPILL_LIBRARY`): mappen som
begynner med episodenummeret, og der den største `.mp3`-en som ikke heter
`_enriched`. Gi en sti som første argument for å overstyre.

Scriptet gjør:

1. Dekoder lyd via PyAV (ffmpeg-bundled)
2. Henter episode-metadata fra RSS-feeden (cached lokalt i `.cache/`)
3. Bygger automatisk `initial_prompt` fra episodetittel, gjesteliste, kapitler
4. Transkriberer med **NB-Whisper large** (norsk-optimert)
5. Kjører **pyannote speaker diarization** (community-1) og matcher mot stemmeprofiler
6. Merger: hver cue får `<v Navn>` (eller `<v SPEAKER_XX>`) basert på tidsoverlapp
7. Applikerer `corrections.json` (navn, terminologi)
8. Skriver VTT og printer speaker-preview så du kan identifisere talere

**Ytelse:** ~12x sanntid totalt på GPU (en 83 min episode tok 7 min).
Whisper kjører i batched-modus som standard. På episode 136 fanget den
opp ~10 min tale som den sekvensielle dekoderen hoppet over, i tillegg
til å være dobbelt så rask. `--sequential` gir den gamle oppførselen.

**Rå-cache:** hver kjøring lagrer Whisper-segmenter, diarisering og
talerkart i `.cache/raw/<navn>.json`. `--render-only` med samme `-o`
bygger VTT-en på nytt derfra på et sekund, uten GPU. Bruk det til å
prøve nye rettelser, `--speaker-map`, `--line-width` eller
`--max-cue-seconds`.

Felles kode for alle transkripsjonsscriptene (lydlasting, CUDA-stier,
diarisering, profilmatching, rettelser, VTT-parsing) ligger i
`scripts/asr_common.py`. Kjør alltid via `uv run python scripts/<script>.py`
slik at prosjektets venv med CUDA-hjulene brukes.

## Typiske CLI-flagg

| Flagg | Beskrivelse |
|---|---|
| `--episode-number N` | Auto-henter metadata fra RSS for episode N |
| `--episode-title "Stunt"` | Alternativt: match tittel-fragment |
| `--episode-guid "abc..."` | Alternativt: match GUID-fragment |
| `--speakers N` | Eksakt antall talere til diarization |
| `--min-speakers N` / `--max-speakers N` | Grenser i stedet for eksakt antall (community-1 teller selv innenfor) |
| `--profiles FILE` | Stemmeprofiler (`transcripts/speaker_profiles.npy`) for auto-navngiving |
| `--profile-threshold 0.65` | Minste likhet for at en profil godtas |
| `--speaker-map "SPEAKER_00=Sigve,..."` | Map talere til navn direkte |
| `--no-diarization` | Hopp over pyannote (raskere, ingen `<v>`-tags) |
| `--diarization-model` | pyannote-pipeline. Standard `pyannote/speaker-diarization-community-1`; `pyannote/speaker-diarization-3.1` er den gamle |
| `--no-exclusive` | Bruk rå, overlappende diarisering i stedet for pipelinens én-taler-om-gangen-utgang |
| `--sequential` | Gammel sekvensiell Whisper-dekoding i stedet for batched (standard) |
| `--batch-size 8` | Batchstørrelse for batched dekoding |
| `--render-only` | Bygg VTT på nytt fra `.cache/raw/` uten GPU |
| `--initial-prompt "..."` | Overstyr auto-prompt med egne termer |
| `--refresh-rss` | Tving ny nedlasting av RSS (ellers brukes 24h cache) |
| `--corrections FILE` | Bruk annen rettelsesordliste |
| `--vad-threshold 0.3` / `--no-vad` | Silero VAD-følsomhet, eller skru VAD helt av |

## Etter transkripsjon: identifiser talere

Scriptet printer 3 eksempel-setninger per taler ved slutt:

```
--- Speaker preview (first 3 utterances each) ---
  SPEAKER_00 [00:00:48]: Jeg heter Sigve, og dette er CD-spill.
  SPEAKER_01 [00:01:36]: Jeg ble sendt hjem fra skolen, til rektor...
  SPEAKER_02 [00:02:35]: Næfjord er jo fordi det er der jeg er fra.
```

Kjør så på nytt med `--speaker-map`, bruk `scripts/add_speakers.py` for å
re-tagge uten å transkribere på nytt, eller bare gjør en tekst-replace i
VTT-filen.

## Stemmeprofiler

`transcripts/speaker_profiles.npy` (ikke i git) inneholder én embedding per
kjent person. Profilene bygges med embedding-modellen inne i
diariserings-pipelinen, og matching nekter å sammenligne profiler med en
annen dimensjon enn pipelinen gir. 3.1 og community-1 bruker samme
wespeaker-modell (256-dim), så eksisterende profiler fungerer med begge.
Bytter du til en pipeline med annen embedding, bygg profilene på nytt med
`build_profiles_clean.py` (rene enkeltspor) eller `build_speaker_profiles.py`
(fra en ferdig tagget VTT).

## Prerequisites

- **NVIDIA GPU**. CPU-fallback er veldig tregt.
- **HF_TOKEN** i `.env`-fila (for pyannote). Godta lisens på:
  - https://huggingface.co/pyannote/speaker-diarization-community-1 (standard)
  - https://huggingface.co/pyannote/speaker-diarization-3.1 (gammel, via `--diarization-model`)
  - https://huggingface.co/pyannote/segmentation-3.0
- Uten HF_TOKEN: bruk `--no-diarization` flagg
- Systemets ffmpeg er ikke nødvendig: lyd dekodes med PyAV. pyannote
  advarer om at torchcodec mangler libavutil, det kan ignoreres.

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
