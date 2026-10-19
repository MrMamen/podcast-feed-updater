# Konfigurasjon

Alt som er spesifikt for én podcast ligger i `podcasts/<id>/`. Koden i `src/`
er generell, og leser oppsettet fra disse filene:

```
podcasts/
├── cdspill/
│   ├── podcast.toml          # beriking av feeden (denne fila)
│   ├── permanent_staff.json  # faste verter (podcast:person på kanalnivå)
│   ├── known_guests.json     # gjester med Podchaser-bilde/-URL og alias (guests.py)
│   ├── chapters/             # lokale kapittelfiler som går foran kildens
│   └── chapter-images/       # bilder for faste kapitler (musikk, tech, ...)
└── tiltcast/
    ├── list.toml             # listefeed fra en Podchaser-liste (build_list_feed.py)
    └── images/
```

`<id>` er mappenavnet, og brukes i filnavn og på kommandolinja:

```bash
uv run enrich.py --podcast cdspill
uv run guests.py --podcast cdspill list
uv run analyze.py --podcast cdspill rank
```

Uten `--podcast` brukes miljøvariabelen `PODCAST`, eller den eneste podcasten som
har en `podcast.toml`. Tilsvarende for `build_list_feed.py --list` / `LIST`.

## Ny podcast

1. Kopier [podcast.example.toml](podcast.example.toml) til `podcasts/<id>/podcast.toml`.
2. Fyll inn `[podcast] source_feed` og `[publish] base_url`, og slå på de stegene du vil ha.
3. Kjør `uv run guests.py --podcast <id> cache` og deretter
   `uv run enrich.py --podcast <id> --local-cache`, og se på `output/<feed>`.
4. For publisering: kopier `.github/workflows/enrich-feed.yml`, bytt `--podcast cdspill`
   og filnavnene. Se [DEPLOYMENT.md](DEPLOYMENT.md).

Valgfritt: `permanent_staff.json` for verter, og `uv run guests.py --podcast <id>` for
gjester (krever Podchaser-nøkler, se [PERSON_DATA_README.md](PERSON_DATA_README.md)).

## Hvordan stegene kjøres

`enrich.py` kjører stegene i en fast rekkefølge (`src/enrichment/pipeline.py`). Et steg
kjøres bare når seksjonen eller valget finnes i `podcast.toml`:

| # | Steg | Styres av |
|---|------|-----------|
| 1 | Stopp hvis kildefeeden allerede har taggene vi legger til | alltid |
| 2 | Fjern episodenummer fra titlene | `[titles] remove_episode_numbers` |
| 3 | Faste verter på kanalnivå | `permanent_staff.json` |
| 4 | `podcast:guid` | `[podcast] guid` |
| 5 | `podcast:season` / `podcast:episode` fra `itunes:season`/`itunes:episode` | alltid, navn fra `[seasons]` |
| 6 | Gjester fra titler og `extra_episodes` | `[titles] guest_pattern`, `known_guests.json` |
| 7 | `podcast:funding` | `[funding]` |
| 8 | `podcast:medium` | `[podcast] medium` |
| 9 | `podcast:updateFrequency` | `[update_frequency]` |
| 10 | `podcast:podroll` | `[[podroll]]` |
| 11 | `podcast:socialInteract` på kanalnivå | `[[social_interact]]` |
| 12 | `podcast:socialInteract` per episode (Bluesky-post) | `[bluesky]` + `episode_article_domain` |
| 13 | Fjern `itunes:summary` / `content:encoded` | `[publish] remove_*` |
| 14 | Fotnote i beskrivelsen | `[description_footer]` |
| 15 | OP3-prefiks | `[publish] op3` |
| 16 | `language` på `podcast:transcript`, versjonerte URL-er | `[transcripts]` |
| 17 | Kapitler: lokale filer, bilder, Apple-lenker, egen hosting | `[chapters]` |
| 18 | `atom:link`, `generator`, `lastBuildDate`, pubDate-eksperiment | `[publish]` |

## `podcast.toml`

Stier er relative til podcastens mappe. Ukjente seksjoner gir feil, så skrivefeil
oppdages.

### `[podcast]`

| Nøkkel | Standard | Betydning |
|--------|----------|-----------|
| `source_feed` | **påkrevd** | Feeden som berikes |
| `name` | `<id>` | Visningsnavn i logger og rapporter |
| `guid` | – | `podcast:guid`. Fallback-testvariantene avleder sine guid-er fra den |
| `medium` | – | `podcast:medium` (`podcast`, `music`, ...) |
| `timezone` | `UTC` | Tidssone for `lastBuildDate` og for å matche Bluesky-poster på dato |
| `episode_article_domain` | – | Nettsted der episodens `<link>` er en artikkel (Bluesky og fotnote) |
| `apple_podcast_id` | – | For kapittellenker til andre episoder i Apple Podcasts |
| `apple_country` | `us` | Apple Podcasts-butikk for de lenkene |
| `podchaser_id` | – | Podchaser-id, brukt av `guests.py episode` |

### `[publish]`

| Nøkkel | Standard | Betydning |
|--------|----------|-----------|
| `base_url` | **påkrevd** | Offentlig URL for `output/` (f.eks. GitHub Pages) |
| `feed` | `<id>-enriched.xml` | Filnavn for den berikede feeden |
| `generator` | `podcast-feed-updater v1.0` | Innholdet i `<generator>` |
| `op3` | `false` | Prefiks lydfilene med `https://op3.dev/e/` |
| `remove_itunes_summary` | `false` | Fjern `itunes:summary` fra episodene |
| `remove_content_encoded` | `false` | Fjern `content:encoded` fra episodene |
| `shift_latest_pubdate_hours` | – | Eksperiment: flytt nyeste episodes `pubDate` så mange timer |

### `[titles]`

Hvordan episodetitlene er skrevet. cd SPILL: `"Spill med Gjest A og Gjest B (#123)"`.

| Nøkkel | Standard | Betydning |
|--------|----------|-----------|
| `remove_episode_numbers` | `false` | Fjern episodenummeret fra titlene (YouTube-varianten setter det inn igjen) |
| `episode_number_suffix` | `'\s*\(#?\d+\)$'` | Regex for episodenummeret på slutten |
| `guest_pattern` | – | Regex der gruppe 1 er gjesten(e), f.eks. `'med (.+?)(?:\s*\(\|$)'`. Uten: ingen gjester fra titler |
| `guest_separator` | – | Ord mellom flere gjester, `"og"` eller en liste (`["and", "&"]`) |
| `subject_separator` | – | Teksten mellom tema og gjester (`" med "`). Brukes til å koble kapitler til andre episoder |

Bruk enkle anførselstegn (`'...'`) rundt regex i TOML, så slipper du å doble `\`.

### `[seasons]`

Navn på `podcast:season`. Uten seksjonen får sesongene bare nummer.

| Nøkkel | Standard | Betydning |
|--------|----------|-----------|
| `naming` | – | `"half_year"`: to sesonger i året fra `first_year`. `"format"`: `name_format` for alle |
| `first_year` | – | Året sesong 1 startet (`half_year`) |
| `half_year_names` | `["Spring", "Fall"]` | Navn på første og andre halvår: `["Vår", "Høst"]` gir «Vår 2020», «Høst 2020», ... |
| `name_format` | `"Season {season}"` | Navn for `format`, og for sesong 0 og lavere |

### `[guests]`

| Nøkkel | Standard |
|--------|----------|
| `known_guests` | `known_guests.json` |
| `permanent_staff` | `permanent_staff.json` |

Formatet er beskrevet i [PERSON_DATA_README.md](PERSON_DATA_README.md).

### `[funding]`

`url` (påkrevd), `message` (teksten i taggen) og `name` (lenketekst i fotnoten, f.eks. `"Patreon"`).

### `[update_frequency]`

`complete` (`true` når podcasten er ferdig), `frequency`, `dtstart` og `rrule`, se
[podcast:updateFrequency](https://podcasting2.org/docs/podcast-namespace/tags/update-frequency).

### `[[podroll]]`

Én tabell per anbefalt podcast: `url` (feed), `title` og `feed_guid`.

### `[[social_interact]]`

Én tabell per konto: `protocol` (`disabled`, `activitypub`, `atproto`, ...), `uri`,
`account_id`, `account_url` og `priority`.

### `[bluesky]`

`handle`: kontoen som poster episodene. Hver episode får en `podcast:socialInteract`
til posten som lenker til episodens artikkel (krever `episode_article_domain`). Poster
uten lenke matches på dato når det er entydig.

### `[description_footer]`

Fotnote som legges til `<description>` (og `content:encoded`):

| Nøkkel | Standard | Betydning |
|--------|----------|-----------|
| `article_prefix` | – | Tekst før artikkellenken. Lenken kommer bare når både denne og `episode_article_domain` er satt |
| `article_text` | `"an article about the episode"` | Lenketeksten |
| `discussion_text` | – | Tekst før lenken til episodens Bluesky-post |
| `funding_text` | – | Tekst før funding-lenken (krever `[funding]`) |
| `follow_text` | `"Follow us on"` | Tekst før de sosiale lenkene |
| `and_word` | `"and"` | Ordet før siste lenke |
| `social_links` | `[]` | `[{ name = "Bluesky", url = "..." }, ...]` |

### `[transcripts]`

| Nøkkel | Betydning |
|--------|-----------|
| `language` | `language`-attributt på alle `podcast:transcript` (påkrevd av Apple Podcasts) |
| `language_overrides` | Unntak: `{ "<del av guid>" = "en" }` |
| `version_podbean_urls` | Legg `?v=<ETag>` på Podbean-URL-er, så nye transkripsjoner endrer feeden |

### `[chapters]`

Kapittelfilene (`podcast:chapters`) lastes ned, eller leses fra `source_dir` når det
finnes en fil med samme navn. De sorteres, får et intro-kapittel ved 00:00 hvis det
mangler, får bilder og lenker, og publiseres under `publish_path`.

| Nøkkel | Standard | Betydning |
|--------|----------|-----------|
| `source_dir` | `chapters` | Lokale kapittelfiler, med samme filnavn som i kildefeeden |
| `images_dir` | – | Bilder for faste kapitler, publiseres under `<publish_path>/images/` |
| `publish_path` | `chapters/<id>` | Under `output/` og `base_url` |
| `apple_links` | `false` | Kapitler som viser en annen episodes cover lenker til den i Apple Podcasts (krever `apple_podcast_id`) |
| `image_rules` | `[]` | Se under |
| `cross_references` | `[]` | Se under |

#### Kapittelbilder

Kapitler som mangler `img` får bilde etter denne rekkefølgen (første treff vinner,
`"img": null` i kapittelfila slår det av):

1. Første kapittel: episodens cover.
2. `[[chapters.image_rules]]`, i rekkefølge.
3. Lenke til Steam, GOG eller Wikipedia: spillets cover.
4. Tittelen matcher det en annen episode handler om (`subject_separator`): eksakt,
   som slutt («Historien i Duke Nukem»), som starten («Doom II» → Doom), eller omvendt.
5. `[[chapters.cross_references]]`, i rekkefølge.
6. Mange felles ord med en annen episode.

En **image rule** treffer når tittelen starter med (`starts_with`), inneholder
(`contains`) eller er lik (`equals`) en av tekstene. Store og små bokstaver regnes likt.
`image` er `episode_cover`, `previous_cover`, `next_cover`, `podcast_logo`, en fil i
`images_dir` eller en full URL. Mangler bildet (f.eks. ingen neste episode), prøves neste regel.

```toml
[[chapters.image_rules]]
image = "previous_cover"
contains = ["fra sist", "fra forrige"]
```

En **cross reference** er en frase der resten av tittelen er navnet på en annen
episode (`starts_with` eller `contains`). `match` sier hvordan navnet sammenlignes:
`"exact"` (hele navnet), `"contains"` (inneholder episodenavnet) eller `"words"`
(felles ord). `unless_contains` hopper over titler med disse tekstene.

```toml
[[chapters.cross_references]]
contains = ["ligner på"]  # "Ligner på Doom" → Doom-episodens cover
match = "exact"
```

### `[variants.<navn>]`

Varianter bygges fra den publiserte berikede feeden (`--local-cache`: fra `output/`):

```bash
uv run enrich.py --podcast cdspill --variant youtube
```

| Variant | Hva den gjør | Nøkler |
|---------|--------------|--------|
| `youtube` | Episodenummer tilbake i titlene, kapitler som tidskoder i beskrivelsen, ingen kapittel-tagger | `feed`, `generator`, `episode_number_format` (`" (#{episode})"`), `shift_latest_pubdate_hours` |
| `spotify` | `psc:chapters` inline i stedet for `podcast:chapters` | `feed`, `generator`, `shift_latest_pubdate_hours` |
| `fallback-test` | Tre testfeeder som mangler hvert sitt beskrivelsesfelt, for å se hva klienter faller tilbake til | `feed_prefix` (`<id>-test-`) |

## `list.toml`

Listefeeder fra en Podchaser-liste er beskrevet i
[tiltcast-list-feed.md](tiltcast-list-feed.md).
