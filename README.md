# Podcast Feed Updater

Beriker en eksisterende podcast-feed med [Podcasting 2.0](https://podcasting2.org)-tagger
og publiserer den på GitHub Pages. Alt som er spesifikt for én podcast ligger i
`podcasts/<id>/podcast.toml`. Koden er generell. cd SPILL (`podcasts/cdspill/`) er
podcasten repoet er laget for, og et fullstendig eksempel.

**Ny podcast:** se [docs/CONFIGURATION.md](docs/CONFIGURATION.md#ny-podcast).

## Hva vil du gjøre?

| Jeg vil … | Kjør |
|---|---|
| Generere den berikede feeden lokalt | `uv run enrich.py [--local-cache]` |
| Generere YouTube-/Spotify-varianten | `uv run enrich.py --variant youtube` / `spotify` |
| Endre hva som legges til i feeden | Rediger `podcasts/cdspill/podcast.toml` ([alle valg](docs/CONFIGURATION.md)) |
| Legge til eller oppdatere gjester | `uv run guests.py` (meny), eller `add "Navn"` / `refresh` / `sync` / `episode "#106"` |
| Se statistikk over gjester og varighet | `uv run analyze.py` (meny), eller `rank` / `guest "Navn"` / `length` |
| Bygge Tiltcast-listefeeden | `uv run build_list_feed.py --list tiltcast` ([mer](docs/tiltcast-list-feed.md)) |

Alle kommandoene tar `--podcast <id>`. Finnes det bare én `podcast.toml`, velges den
automatisk. `guests.py cache` og `analyze.py cache` laster ned kildefeeden til `.cache/`,
som `--local-cache` bruker.

## Hva legges til

Avhengig av `podcast.toml`:

- **Personer:** faste verter, og gjester fra episodetitlene med Podchaser-bilde og -lenke
- **Kanal:** guid, funding, medium, oppdateringsfrekvens, podroll, sosiale kontoer
- **Episoder:** sesong og episode (med sesongnavn), Bluesky-tråd per episode, fotnote i
  beskrivelsen, OP3-statistikk, språk på transkripsjoner
- **Kapitler:** egne kapittelfiler (med skjulte kapitler og lenker), automatiske
  kapittelbilder og lenker til andre episoder, hostet på GitHub Pages
- **Varianter:** YouTube (episodenummer og tidskoder i beskrivelsen) og Spotify (`psc:chapters`)

## Oppsett

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # uv håndterer Python og avhengigheter
uv run guests.py cache                            # last ned kildefeeden
uv run enrich.py --local-cache                    # skriver output/<feed>
```

Podchaser-nøkler (`PODCHASER_API_KEY` og `PODCHASER_API_SECRET` i `.env`) trengs bare for
`guests.py` og listefeeden. Publisering med GitHub Actions: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Struktur

```
enrich.py            berik en feed, og bygg varianter (--variant)
guests.py            vedlikehold gjester (Podchaser)
analyze.py           rapporter
build_list_feed.py   feeder fra en Podchaser-liste
pubnotify.py         varsle Podcast Index etter publisering
podcasts/<id>/       podcast.toml, gjester, kapittelfiler og bilder per podcast
src/config.py        leser podcast.toml
src/enrichment/      pipeline (stegene), FeedEnricher (én modul per tema), varianter
src/common/          feed, gjester, titler og episoder
src/listfeed/        listefeeder
output/              generert, publiseres til GitHub Pages
```

Utvikling: `uv run ruff check .`

## Lisens

MIT
