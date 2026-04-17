# Podcast Feed Updater

En Python-tjeneste for å berike podcast RSS feeds med Podcasting 2.0 tags.

## 🎯 Use Case: cd SPILL Feed Enrichment
Berik en eksisterende feed med Podcasting 2.0 tags.

**Se [docs/ENRICHMENT_GUIDE.md](docs/ENRICHMENT_GUIDE.md)** for komplett dokumentasjon.

```bash
# Normal bruk (henter fra nettet)
uv run enrich_cdspill.py

# Lokal testing med cached feed (for utvikling)
uv run python3 scripts/download_cdspill_cache.py  # Last ned cache først
uv run enrich_cdspill.py --local-cache             # Bruk lokal cache

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
│   ├── common/                # Felles utilities (feed, guests, utils)
│   └── enrichment/            # FeedEnricher + Podchaser API
├── enrich_cdspill.py          # Hovedscript (Podcasting 2.0 enrichment)
├── enrich_cdspill_spotify.py  # Spotify-variant (kjøres av CI)
├── enrich_cdspill_youtube.py  # YouTube-variant (kjøres av CI)
├── config/                    # JSON-config (gjester, faste roller)
├── chapters/                  # Kapittel-data per episode (kilde)
├── scripts/
│   ├── guests/                # Podchaser-verktøy: lookup, populate, osv.
│   ├── analysis/              # Ad hoc rapporter (rank, list, …)
│   ├── download_cdspill_cache.py  # Dev-utility
│   └── (transkribe-pipeline)
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

Person data (hosts og gjester) vedlikeholdes i JSON-filer. Podchaser brukes for å berike med profil-URLs:

```bash
# Auto-populate alle gjester fra episode-titler
uv run python3 scripts/guests/populate_guests.py

# Legg til gjest fra Podchaser URL (interaktiv matching med piltaster)
uv run python3 scripts/guests/add_guest_from_url.py "https://www.podchaser.com/creators/name-id"

# Legg til enkelt-gjest ved søk
uv run python3 scripts/guests/lookup_guest.py "Guest Name"
```

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
