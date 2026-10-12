# Transcripts

Publiserbare VTT-transcripts for podcast-episoder, og verktøy for å lage nye.

## Innhold

- `*.vtt` — publiserbare transcripts (én per episode, ikke i git)
- `corrections.json` — permanent rettelsesordliste (egennavn, terminologi) som gjelder alle episoder
- `TRANSCRIPT_GUIDELINES.md` — stilreglene transkriptene følger
- `<episode>.review.md` — midlertidige sjekklister etter en språkvask (ikke i git)

## Arbeidsflyt for en episode du har klippet selv

Episodemappa har Reaper-prosjektet og ett opptak per mikrofon. Da er
dette hele løpet, uten pyannote:

```bash
uv run python scripts/transcribe.py -o transcripts/Episode.vtt --episode-number 130 --no-diarization
uv run python scripts/align_solo.py  -o transcripts/Episode.vtt --episode-number 130
uv run python scripts/transcribe.py -o transcripts/Episode.vtt --render-only
```

Deretter språkvasken: `scripts/claude-tools/language_pass.py split` deler
VTT-en i ti-minutters biter ved nærmeste pause, med soloteksten og nabocuene
som referanse og en ferdig instruks per bit; én subagent redigerer hver bit;
`join` setter sammen igjen, `measure` sier hva som ble endret, og `names`
lister navn som er stavet ulikt i ulike biter. Til slutt `transcribe.py
--polish`, og det samme etter hver runde med håndredigering. Detaljer om
hvert steg under.

## `scripts/transcribe.py`

For å transkribere en episode fra audio, med pyannote-diarisering når det
ikke finnes solospor:

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
| `--polish` | Rydd en håndredigert VTT på plass: del markerte to-taler-cues når begge deler er lesbare (eller slå en for kort del sammen med nabocuen til samme taler), kjør ordlista, flytt grensen mellom to cuer som henger sammen til pausen mellom ordene deres (soloordene; fanger tekst som er flyttet fra én cue til en annen), skyv cue-slutter 0,5 s inn i pausen etter, strekk cues over stillheten der taleren fortsatt snakker på solosporet (aldri inn i neste/forrige cue eller en annen talers tale), forleng korte cues, brekk om, rapporter cues over 7 s, overlapp, tre linjer og over 25 tegn/s. Uten GPU |
| `--tail-pad 0.5` | Sekunder hver cue-slutt skyves inn i pausen etter (Whisper slutter ordene for tidlig); 0 skrur av |
| `--no-fill-gaps` | Dropp passet som finner tale Whisper hoppet over og transkriberer den på nytt (se TRANSCRIPT_GUIDELINES) |
| `--language auto` | La modellen gjenkjenne språket (bruk med flerspråklig `--model`; NB-Whisper oversetter andre språk til norsk) |
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
VTT-filen. Er talerne innsendte klipp som finnes som egne filer, se
`align_clips.py` under.

## Innsendte klipp: `scripts/align_clips.py`

«Spillåret»-episodene har et dusin lytterbidrag som er spilt inn hver for
seg og klippet inn i mixen. Diarisering av 16 stemmer over 150 minutter er
upålitelig, og tagging etter kapittelstart blir feil når vertene prater
rundt klippet. Ligger klippfilene i episodemappa, finner dette scriptet
dem i mixen (krysskorrelasjon av bånd-energi, tåler gain/EQ/musikkseng),
og skriver om rå-cachen fra `transcribe.py` slik at klippets talespenn får
én diariseringstur med riktig navn og mixteksten der byttes ut med en
transkripsjon av det rene klippet (kjøres automatisk med
`--no-diarization` når den mangler).

```bash
uv run python scripts/transcribe.py -o transcripts/1995.vtt --episode-number 125 \
  --profiles transcripts/speaker_profiles.npy --min-speakers 2 --max-speakers 20
uv run python scripts/align_clips.py -o transcripts/1995.vtt --episode-number 125 \
  --clips clips125.json          # {"worms_spruceman.wav": "Roar Granevang", ...}
uv run python scripts/transcribe.py -o transcripts/1995.vtt --render-only
```

Klipp som er spilt av litt raskere i mixen (Reaper-rate, opptil ~5 % sett i
praksis) får tilpasset både offset og hastighet, så ordtidene stemmer helt til
slutten; `--locate-only` viser `rate x0.956` når det skjer. Klipp under ~10 s
finnes ikke av søket og må tagges for hånd.

`--clip "fil=Navn"` kan gis i stedet for JSON. Bruk fullt profilnavn;
rollenavn for figurer (`Kato`), og `Navn|en` for engelske innslag (sang)
så klippet ikke blir oversatt. `--locate-only` viser bare hvor klippene
ligger. Originalcachen bevares som `.cache/raw/<navn>.orig.json`, så
scriptet kan kjøres om igjen med en rettet mapping.

## Solospor og Reaper-prosjektet: `scripts/align_solo.py`

Episoder som er klippet i Reaper har `.rpp`-fila og ett opptak per mikrofon
i mappa. Prosjektfila lister hvert klipp på hvert spor med posisjon i mixen,
lengde og offset i kildefila, og er dermed en eksakt fasit for hvem som
høres når, og for hvilke sekunder av hvert solospor som overlevde klippingen.
Dette scriptet transkriberer solosporene hver for seg (uten diarisering),
flytter ordene inn i mix-tid via klippene, og skriver om rå-cachen slik at

- talertaggene kommer fra soloordene (pyannote brukes ikke; Reaper-klippet
  er reserve der ingen soloord finnes),
- tale mixen hoppet over fylles fra soloordene (samme regel som gap-fyllet),
- ord på solosporet som fortsetter samme taler rett etter at mixteksten
  stopper (setningshaler som «… grid to prefectures»), legges til
  segmentet uansett hvor kort hullet er,
- filene på de andre sporene (musikk, effekter, spillklipp) sjekkes med
  Silero VAD; de som inneholder tale transkriberes fra den rene fila med
  en flerspråklig modell og automatisk språkgjenkjenning, og erstatter
  mixteksten i sitt spenn med taggen `Spillklipp`. `--item "fil.wav=Gabriel"`
  setter rollenavn (og eventuelt språk, `|en`) på et klipp. Et produsert
  innslag som ligger på en talers spor (intro, sketsj) regnes som den
  mikrofonen med mindre det gis med `--item`,
- mixord som ligger i musikk-/effektspenn uten mikrofon-item eller soloord
  i nærheten fjernes som hallusinasjoner,
- spenn der et mikrofon-item finnes men solosporet ikke ga ord (dropout)
  listes, siden taggen der kommer fra klippet og ikke fra ordene,
- den kartlagte soloteksten lagres som `solo_segments` i cachen, som
  referanse for språkvasken.

```bash
uv run python scripts/transcribe.py -o transcripts/TA.vtt --episode-number 120 --no-diarization
uv run python scripts/align_solo.py -o transcripts/TA.vtt --episode-number 120 \
  --item "Total Annihilation - Intro Cinematic.wav=Forteller"
uv run python scripts/transcribe.py -o transcripts/TA.vtt --render-only
```

Sporene gjenkjennes på navn: vertenes spor («Mamen», «Sigve»), et spor med
navnet til en gjest fra episodens `podcast:person`-liste eller stemmeprofilene
(fornavn holder), eller eksplisitt `--track "Roar=Roar Granevang"`. Spor som
ikke matcher noen regnes som musikk/effekter. `--list` viser spor og filer og
stopper. Klippene transkriberes med `--item-model` (standard
`Systran/faster-whisper-large-v3`) og `--language auto`: NB-Whisper oversetter
engelske klipp til norsk selv med `--language en`. `--no-auto-items` tar bare
klippene gitt med `--item`. Målt på episode 120: pyannote satte feil taler på 8 % av cuene selv
med profil-likhet over 0,93; solosporene fanget 6 % flere ord enn mixen.

## Talernavn

Profiler og RSS-metadata bruker fullt navn, men `<v>`-taggene i VTT-en
bruker kortform: verter og gjester med fornavn (`Mamen`, `Sigve`,
`Jostein`). Unntak legges under `"speaker_names"` i `corrections.json`,
f.eks. `{"Joachim Froholt": "Joachim F."}` hvis to gjester deler fornavn.
Stemmer fra spill- og filmklipp tagges for hånd med rollenavn
(`Picard`, `Garidiansk kaptein`).

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

Spillterminologi som kommer igjen i flere episoder (Schattenjäger, Cabrit
sans cor) hører også hjemme her. **Episode-spesifikke** rettelser (ett
bestemt ord som kun nevnes én gang) gjøres direkte i VTT-en.

## Publisering

Etter du har en ferdig `.vtt`:

1. Last opp til din hosting-provider (podbean el.l.)
2. Legg til `<podcast:transcript url="..." type="text/vtt" language="nb"/>` i RSS-feeden for episoden
3. Apple Podcasts, Podverse, Fountain og andre podcasting-2.0-spillere vil vise transkripsjonen din fremfor auto-genererte
