# Konfigurasjon

Alt som er spesifikt for én podcast ligger i `podcasts/<id>/`:

```
podcasts/cdspill/
├── podcast.toml          # hva som legges til i feeden (denne fila)
├── permanent_staff.json  # faste verter
├── known_guests.json     # gjester, vedlikeholdes med guests.py
├── chapters/             # lokale kapittelfiler, går foran kildens
└── chapter-images/       # bilder for faste kapitler
```

Kommandoene velger podcast med `--podcast <id>`, miljøvariabelen `PODCAST`, eller den eneste
som finnes. Stier i `podcast.toml` er relative til mappen, og ukjente seksjoner gir feil.

## Ny podcast

1. Kopier [podcast.example.toml](podcast.example.toml) til `podcasts/<id>/podcast.toml`,
   og fyll inn `source_feed` og `base_url`.
2. `uv run guests.py --podcast <id> cache` og `uv run enrich.py --podcast <id> --local-cache`,
   og se på resultatet i `output/`.
3. Publisering: se [DEPLOYMENT.md](DEPLOYMENT.md).

Et steg kjøres bare når seksjonen eller valget finnes. Rekkefølgen er fast, se
`src/enrichment/pipeline.py`.

## `[podcast]`

| Nøkkel | Standard | Betydning |
|--------|----------|-----------|
| `source_feed` | **påkrevd** | Feeden som berikes |
| `name` | `<id>` | Visningsnavn |
| `guid` | – | `podcast:guid` |
| `medium` | – | `podcast:medium` |
| `timezone` | `UTC` | For `lastBuildDate` og Bluesky-datoer |
| `episode_article_domain` | – | Nettsted der episodens `<link>` er en artikkel (Bluesky og fotnote) |
| `apple_podcast_id` / `apple_country` | – / `us` | For kapittellenker til andre episoder |
| `podchaser_id` | – | For `guests.py episode` |

## `[publish]`

| Nøkkel | Standard | Betydning |
|--------|----------|-----------|
| `base_url` | **påkrevd** | Offentlig URL for `output/` |
| `feed` | `<id>-enriched.xml` | Filnavn |
| `generator` | `podcast-feed-updater v1.0` | `<generator>` |
| `op3` | `false` | OP3-prefiks på lydfilene |
| `remove_itunes_summary`, `remove_content_encoded` | `false` | Fjern disse feltene fra episodene |
| `shift_latest_pubdate_hours` | – | Eksperiment: flytt nyeste episodes `pubDate` |

## `[titles]` og `[seasons]`

Hvordan titlene skrives, f.eks. `"Spill med Gjest A og Gjest B (#123)"`. Bruk `'...'` rundt regex.

| Nøkkel | Betydning |
|--------|-----------|
| `remove_episode_numbers` | Fjern episodenummeret (`episode_number_suffix`, standard `'\s*\(#?\d+\)$'`) |
| `guest_pattern` | Regex der gruppe 1 er gjestene: `'med (.+?)(?:\s*\(\|$)'` |
| `guest_separator` | Ord mellom gjester: `"og"`, eller en liste |
| `subject_separator` | Mellom tema og gjester (`" med "`), for å koble kapitler til andre episoder |

`[seasons]` gir `podcast:season` et navn: `naming = "half_year"` med `first_year` og
`half_year_names = ["Vår", "Høst"]` gir «Vår 2020», «Høst 2020», … `naming = "format"` bruker
`name_format` (`"Season {season}"`). Uten seksjonen får sesongene bare nummer.

## Verter og gjester

`permanent_staff.json` gir verter på kanalnivå:

```json
{"hosts": [{"name": "Navn", "role": "host", "img": "https://…", "href": "https://…"}]}
```

`known_guests.json` gir gjestene i titlene bilde og lenke. Nøkkelen er det offisielle
Podchaser-navnet. Andre skrivemåter fra titlene legges inn som alias. `extra_episodes`
legger en gjest til episoder der navnet ikke står i tittelen:

```json
{
  "guests": {"Fullt Navn": {"img": "…", "href": "…",
                            "extra_episodes": [{"guid": "…", "note": "Tittel (#106)"}]}},
  "aliases": {"Kort Navn": "Fullt Navn"}
}
```

Vedlikehold fila med `guests.py`. Den fyller bare inn det som mangler, og overskriver aldri.
Hvert oppslag koster rundt 10 Podchaser-poeng. Filnavnene kan endres i `[guests]`.

## Kanal og sosiale medier

- `[funding]`: `url`, `message`, og `name` (lenketekst i fotnoten).
- `[update_frequency]`: `complete`, `frequency`, `dtstart`, `rrule`
  ([spec](https://podcasting2.org/docs/podcast-namespace/tags/update-frequency)).
- `[[podroll]]`: `url`, `title`, `feed_guid` per podcast.
- `[[social_interact]]`: `protocol`, `uri`, `account_id`, `account_url`, `priority` per konto.
- `[bluesky] handle`: hver episode får en lenke til Bluesky-posten som lenker til
  episodeartikkelen. Krever `episode_article_domain`.

## `[description_footer]`

Legges til episodebeskrivelsen. Alle tekstnøklene er valgfrie:

| Nøkkel | Gir |
|--------|-----|
| `article_prefix`, `article_text` | «Spillhistorie har skrevet [en artikkel om episoden].» |
| `discussion_text` | «Diskuter episoden på [Bluesky].» |
| `funding_text` | «Støtt oss gjerne på [Patreon].» (krever `[funding]`) |
| `follow_text`, `and_word`, `social_links` | «Følg oss gjerne på [Bluesky], [X] og [Facebook].» |

## `[transcripts]`

`language` settes på alle `podcast:transcript`, med unntak i `language_overrides = { "<del av guid>" = "en" }`.
`version_podbean_urls = true` legger `?v=<ETag>` på Podbean-URL-er, så en erstattet
transkripsjon endrer feeden.

## `[chapters]`

| Nøkkel | Standard | Betydning |
|--------|----------|-----------|
| `source_dir` | `chapters` | Lokale kapittelfiler, med samme filnavn som i kildefeeden |
| `images_dir` | – | Bilder for faste kapitler |
| `publish_path` | `chapters/<id>` | Under `output/` og `base_url` |
| `apple_links` | `false` | Lenk kapitler med en annen episodes cover til den episoden i Apple Podcasts |

### Kapittelbilder

Kapitler uten `img` får bilde i denne rekkefølgen. Første treff vinner, og `"img": null` slår det av.

1. Første kapittel får episodens cover.
2. `[[chapters.image_rules]]`: tittelen starter med (`starts_with`), inneholder (`contains`)
   eller er lik (`equals`) en tekst. `image` er `episode_cover`, `previous_cover`,
   `next_cover`, `podcast_logo` eller en fil i `images_dir`.
3. En lenke til Steam, GOG eller Wikipedia gir spillets cover.
4. Tittelen matcher det en annen episode handler om («Doom II» → Doom-episoden).
5. `[[chapters.cross_references]]`: en frase som etterfølges av navnet på en annen episode
   («Ligner på Doom»). `match` er `exact`, `contains` eller `words`.
6. Mange felles ord med en annen episode.

Store og små bokstaver regnes likt. Se `podcasts/cdspill/podcast.toml` for eksempler.

## `[variants.<navn>]`

Varianter bygges fra den publiserte berikede feeden (med `--local-cache`: fra `output/`):

| Variant | Endrer | Nøkler |
|---------|--------|--------|
| `youtube` | Episodenummer i titlene, kapitler som tidskoder i beskrivelsen | `feed`, `generator`, `episode_number_format`, `shift_latest_pubdate_hours` |
| `spotify` | `psc:chapters` i stedet for `podcast:chapters` | `feed`, `generator`, `shift_latest_pubdate_hours` |
| `fallback-test` | Tre testfeeder som mangler hvert sitt beskrivelsesfelt | `feed_prefix` |
