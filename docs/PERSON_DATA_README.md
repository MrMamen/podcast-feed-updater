# Person Data System for cd SPILL

## Overview

Simple, manually maintained system for person data (hosts and guests) with optional Podchaser enrichment.

## Files

### `config/cdspill_permanent_staff.json`
Permanent roles that appear at channel level or across many episodes:
- **Hosts**: Appear on every episode (channel-level tags)
- **Other roles**: Production staff like cover art designers, music composers, etc.

Edit this file directly to add/update permanent staff.

### `config/cdspill_known_guests.json`
Guest data with profile images and URLs:
```json
{
  "guests": {
    "Official Name (from Podchaser)": {
      "img": "https://...",
      "href": "https://www.podchaser.com/creators/..."
    }
  },
  "aliases": {
    "Name in Feed": "Official Name (from Podchaser)"
  }
}
```

**Important**: Guest names in the `guests` object should be the official names from Podchaser.
Names used in episode titles that differ should be added as aliases.

## Workflow

Alt vedlikehold av gjester går gjennom `guests.py`. Uten argumenter får du en piltast-meny;
underkommandoene under er for scripting.

```bash
uv run guests.py                                   # interaktiv meny
uv run guests.py add "Guest Name"                  # søk Podchaser, velg treff
uv run guests.py add "https://www.podchaser.com/creators/name-id"
uv run guests.py add "Full Name" --alias "Short Name"
uv run guests.py refresh [Name]                    # fyll inn manglende img/href
uv run guests.py sync                              # nye gjester fra episodetitler
uv run guests.py episode "#106"                    # gjester fra Podchaser-credits
uv run guests.py list                              # oversikt med 📷/🔗-status
```

**Felles regel:** en gjest som allerede finnes overskrives aldri – bare manglende `img`/`href`
fylles inn. Det gjelder uansett om du kommer inn via `add`, `refresh`, `sync` eller `episode`.

### `add` – én gjest fra navn eller URL

1. Søker Podchaser (navn → inntil 5 treff å velge mellom; URL → treffet med matchende id).
2. Finner ut om personen allerede finnes: på `href`, på Podchaser-navn, via alias, eller på navnet
   du søkte på. Finner den ingen, foreslås lignende navn i en meny, med «Legg til som ny» som
   alternativ.
3. Hvis den eksisterende nøkkelen ikke er Podchaser-navnet, spørres det om å bruke Podchaser-navnet
   som hovednavn (det gamle blir alias).
4. Manglende `img`/`href` fylles inn. Hvis navnet du søkte på avviker fra hovednavnet, spørres det
   om å legge det til som alias.

### `refresh` – fyll inn det som mangler

Går gjennom alle gjester (eller én navngitt), slår opp på Podchaser og fyller inn manglende
`img`/`href`. Har gjesten allerede et bilde men Podchaser viser en annen bilde-URL, vises begge og du
får spørsmål om å oppdatere eller beholde. Eksakt navnetreff (eller samme `href`) godtas automatisk;
andre treff må bekreftes. `--yes` hopper over usikre treff og godtar nye bilder uten å spørre.
Koster ett Podchaser-oppslag per gjest.

### `sync` – nye gjester fra episodetitler

Finner alle «med Navn»-gjester i feeden som ikke finnes i fila (verken som gjest eller alias) og
legger dem til. Eksakt Podchaser-treff gir profildata; usikre treff må bekreftes; ikke funnet →
legges til uten data (så `refresh` kan prøve igjen senere).

### `episode` – gjester som ikke står i tittelen

Slår opp episoden (nummer, tittel eller GUID), henter credits fra Podchaser, legger til gjester som
mangler i fila, og registrerer episoden under `extra_episodes` for gjester som ikke står i tittelen.

## Podchaser API Usage

**guests.py sync / refresh**: ~7-10 points per guest looked up
**guests.py add**: ~7-10 points per lookup
**guests.py episode**: one episode search + one credits fetch
**enrich_cdspill.py cost**: 0 points (no API calls)

The enricher runs offline using the JSON files. Podchaser is only used when adding new guests.

## Manual Editing

You can also manually edit `config/cdspill_known_guests.json`:

```json
{
  "guests": {
    "New Guest": {
      "img": "https://creator-images.podchaser.com/hash.jpeg",
      "href": "https://www.podchaser.com/creators/new-guest-id"
    }
  },
  "aliases": {
    "Nickname": "New Guest"
  }
}
```

## Auto-detection

Guests are auto-detected from episode titles using the pattern:
- "med Guest Name" → detects "Guest Name"
- "med Guest1 og Guest2" → detects both guests
- Episode numbers are automatically stripped

### Manual Episode Assignment (extra_episodes)

For guests not mentioned in episode titles, use `extra_episodes` with GUID-based identification:

```json
{
  "guests": {
    "Guest Name": {
      "href": "https://www.podchaser.com/creators/...",
      "img": "https://creator-images.podchaser.com/...",
      "extra_episodes": [
        {
          "guid": "cdspill.podbean.com/053d7b0f-64f8-3a89-88cf-5ec2a8e6f95c",
          "note": "Spillåret 1994 (#106)"
        }
      ]
    }
  }
}
```

Normally you don't edit this by hand – `uv run guests.py episode "#106"` fills it from
Podchaser credits. **Finding the GUID manually:**
```bash
curl -s https://feed.podbean.com/cdspill/feed.xml | grep -A 5 "Episode Title"
```

The `note` field is optional but recommended for human readability. GUIDs are stable identifiers that won't change even if episode titles are modified.

### Detecting Missing Aliases

The enricher helps you identify when aliases are needed. If a guest appears in titles with a different name than in `known_guests`, you'll see:

```
⚠ Found 1 guest(s) without Podchaser URL (href):
  - Anette Vik Jøsendal (6 episodes)
    (detected as 'Anette Jøsendal' in titles)
```

This tells you that:
1. Episodes use "Anette Jøsendal" in titles
2. But the official name in known_guests is "Anette Vik Jøsendal"
3. An alias exists: `"Anette Jøsendal": "Anette Vik Jøsendal"`
4. But the official entry is missing href

To fix: `uv run guests.py refresh "Anette Vik Jøsendal"` (or `add` with the Podchaser URL).

The enricher only warns about missing Podchaser URLs (href attribute), not missing images.

## Current Status

**Permanent hosts**: 2 (Sigve, Mamen)
**Known guests**: 9 with profile images
**Aliases**: 3 name normalizations

Run `uv run enrich_cdspill.py` to see current counts.
