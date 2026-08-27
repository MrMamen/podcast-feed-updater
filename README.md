# Podcast Feed Updater

En Python-tjeneste for å berike podcast RSS feeds med Podcasting 2.0 tags.

## 🧭 Hva vil du gjøre?

| Jeg vil … | Kjør |
|---|---|
| Legge til en ny gjest | `uv run guests.py` (meny) eller `uv run guests.py add "Navn"` / `add <podchaser-url>` |
| Fylle inn manglende bilde/URL, eller hente oppdaterte bilder fra Podchaser | `uv run guests.py refresh [Navn]` |
| Finne nye gjester fra episodetitler | `uv run guests.py sync` |
| Registrere gjester på en episode der de ikke står i tittelen | `uv run guests.py episode "#106"` |
| Se statistikk (rangering, episoder per gjest, varighet) | `uv run analyze.py` (meny) eller `analyze.py rank` / `guest "Navn"` / `length` |
| Generere den berikede feeden lokalt | `uv run enrich_cdspill.py [--local-cache]` |
| Generere Spotify-/YouTube-variantene | `uv run enrich_cdspill_spotify.py` / `enrich_cdspill_youtube.py` |
| Bygge Tiltcast-listefeed | `uv run build_list_feed.py` |
| Transkribere en episode | `uv run python scripts/transcribe.py …` (se [transcripts/README.md](transcripts/README.md)) |

`guests.py` og `analyze.py` uten argumenter gir en piltast-meny; underkommandoene finnes for scripting. Begge har en `cache`-kommando som laster ned en lokal kopi av feeden (`.cache/`), og `analyze.py` laster den ned automatisk hvis den mangler.

## 🎯 Use Case: cd SPILL Feed Enrichment
Berik en eksisterende feed med Podcasting 2.0 tags.

**Se [docs/ENRICHMENT_GUIDE.md](docs/ENRICHMENT_GUIDE.md)** for komplett dokumentasjon.

```bash
# Normal bruk (henter fra nettet)
uv run enrich_cdspill.py

# Lokal testing med cached feed (for utvikling)
uv run guests.py cache                  # Last ned cache først
uv run enrich_cdspill.py --local-cache  # Bruk lokal cache

# Legger til:
# - Hosts og gjester (podcast:person)
# - Sesong/episode tags med navn
# - Funding link (Patreon)
# - Social media integrasjon
# - Update frequency (biweekly)
# - Podroll (anbefalinger)
# - OP3 analytics (privacy-respecting tracking)
# - Podlove Simple Chapters (inline chapter markers)
```

## 🚀 Deployment (Automatisk kjøring)

For å sette opp automatisk feed-enrichment og hosting:

**Quick start (5 minutter):**
```bash
# 1. Push til GitHub
git push origin master

# 2. Aktiver GitHub Pages i repo settings

# 3. Trigger workflow i Actions tab
```

Se **[docs/QUICKSTART_DEPLOYMENT.md](docs/QUICKSTART_DEPLOYMENT.md)** for steg-for-steg guide.

**Resultat:**
- ✅ Automatisk kjøring på mandager (kl 07:00, 09:00, 11:00, 13:00 UTC)
- ✅ Gratis hosting på GitHub Pages
- ✅ Feed URL: `https://[username].github.io/podcast-feed-updater/cdspill-enriched.xml`

Se **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** for full dokumentasjon og alternative løsninger.

---

## 📦 Lokal installasjon

### Med uv (anbefalt)
```bash
# 1. Installer uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Kjør script (uv håndterer alt automatisk)
uv run enrich_cdspill.py
```

### Med pip
```bash
# Opprett virtuelt miljø
python3 -m venv .venv
source .venv/bin/activate

# Installer dependencies
pip install -e .
```

## 🏗️ Arkitektur

```
podcast-feed-updater/
├── src/
│   ├── common/                # Felles utilities (feed_loader, guest_config, guest_store, episodes)
│   ├── enrichment/            # FeedEnricher + Podchaser API
│   └── listfeed/              # Tiltcast-listefeed
├── enrich_cdspill.py          # Hovedscript (Podcasting 2.0 enrichment, kjøres av CI)
├── enrich_cdspill_spotify.py  # Spotify-variant (kjøres av CI)
├── enrich_cdspill_youtube.py  # YouTube-variant (kjøres av CI)
├── enrich_cdspill_fallback_test.py  # Testfeeds for klient-fallback (kjøres av CI)
├── build_list_feed.py         # Tiltcast-listefeed (kjøres av CI)
├── guests.py                  # Gjestevedlikehold: meny + add/refresh/sync/episode/list/cache
├── analyze.py                 # Rapporter: meny + rank/guest/length/cache
├── config/                    # JSON-config (gjester, faste roller, tiltcast-liste)
├── chapters/                  # Kapittel-data per episode (kilde)
├── scripts/
│   ├── transcribe.py, diarize_chapters.py, normalize_transcript.py,
│   │   add_speakers.py, build_speaker_profiles.py, build_profiles_clean.py  # Transkripsjon
│   └── claude-tools/          # Hjelpescript for Claude-sesjoner (ikke podcast-relatert)
├── docs/                      # Markdown-dokumentasjon
└── output/                    # Generert XML (publiseres til GitHub Pages)
```

## ✨ Features

### Podcasting 2.0 Tags Support

**Channel-level:**
- `<podcast:person>` - Hosts og gjester
- `<podcast:funding>` - Funding links (Patreon, etc)
- `<podcast:medium>` - Content type
- `<podcast:updateFrequency>` - Publishing schedule (with rrule)
- `<podcast:podroll>` - Podcast recommendations
- `<podcast:socialInteract>` - Social media integration

**Episode-level:**
- `<podcast:season>` - Season med navn (f.eks. "Vår 2020")
- `<podcast:episode>` - Episode numbers
- `<podcast:person>` - Per-episode guests
- `<podcast:chapters>` - Chapter markers (JSON format, preserved from original)
- `<psc:chapters>` - Podlove Simple Chapters (inline XML format)
- OP3 prefixed enclosures - Privacy-respecting download tracking

### Feed Operations
- **Preserve XML** - Bevarer all original struktur (lxml)
- **Namespace handling** - Korrekt håndtering av itunes:, podcast:, etc.

## 🔧 Person Data

### Podchaser Integration

Person data (hosts og gjester) vedlikeholdes i JSON-filer. Podchaser brukes for å berike med profilbilde og -URL. Alt gjøres via `guests.py`:

```bash
uv run guests.py                       # interaktiv meny
uv run guests.py add "Guest Name"      # søk, velg treff, legg til / fyll inn manglende felt
uv run guests.py add "https://www.podchaser.com/creators/name-id"
uv run guests.py add "Fullt Navn" --alias "Kort Navn"
uv run guests.py refresh [Navn]        # fyll inn manglende bilde/URL, oppdater endrede bilder
uv run guests.py sync                  # nye gjester fra episodetitler
uv run guests.py episode "#106"        # gjester fra Podchaser-credits → extra_episodes
uv run guests.py list
```

En eksisterende gjest overskrives aldri – bare manglende `img`/`href` fylles inn.

**Alias-system**: Offisielle navn fra Podchaser brukes som hovednavn.
Navnevarianter fra episode-titler legges til som aliaser.

**Se [docs/PERSON_DATA_README.md](docs/PERSON_DATA_README.md)** for komplett dokumentasjon.

## 📝 Bruk

### Basic Example - Feed Enrichment

```python
from src.enrichment.enricher import FeedEnricher

# Initialize
enricher = FeedEnricher("https://example.com/feed.xml")
enricher.fetch_feed()

# Add hosts
hosts = [
    {
        "name": "Host Name",
        "role": "host",
        "href": "https://example.com/host"
    }
]
enricher.add_channel_persons(hosts)

# Add funding
enricher.add_funding(
    url="https://patreon.com/show",
    message="Support us on Patreon"
)

# Add medium
enricher.add_medium("podcast")

# Add update frequency
enricher.add_update_frequency(
    complete=False,
    frequency=1,
    dtstart="2020-01-01",
    rrule="FREQ=WEEKLY"
)

# Add podroll
enricher.add_podroll([
    {
        "feedTitle": "Another Podcast",
        "url": "https://example.com/feed.xml",
        "feedGuid": "guid-here"
    }
])

# Write output
enricher.write_feed("output.xml")
```

## 🧪 Development

```bash
# Install with dev dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# Format code
black .

# Lint
ruff check .
```

## 📚 Dependencies

- **lxml** - XML processing (preserves namespaces)
- **requests** - HTTP client
- **python-dotenv** - Environment variables
- **pyyaml** - Config files

## 🤝 Contributing

Pull requests are welcome! For major changes, please open an issue first.

## 📄 License

MIT

## 🔗 Resources

- [Podcasting 2.0 Namespace](https://github.com/Podcastindex-org/podcast-namespace)
- [Podchaser API](https://api-docs.podchaser.com)
- [Podcast Index](https://podcastindex.org)
- [OP3 Analytics](https://op3.dev) - Privacy-respecting download tracking
- [Podlove Simple Chapters](https://podlove.org/simple-chapters/) - Chapter format specification
