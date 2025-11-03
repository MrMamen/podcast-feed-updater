# Podcast Feed Updater

En Python-tjeneste for å filtrere og berike podcast RSS feeds. Perfekt for å:

- **Splitte** kombinerte feeds basert på episode-titler
- **Filtrere** ut spesifikke episoder
- **Berike** feeds med Podcasting 2.0 tags (f.eks. `<podcast:person>`)
- **Hente** creator-informasjon fra Podchaser API

## Funksjoner

### 1. Filtrering av episoder
Filtrer episoder basert på regex-mønstre i tittelen:

```bash
# Behold kun episoder som matcher "Tech Talk"
python3 src/cli.py --source https://example.com/feed.xml \
                   --output filtered.xml \
                   --pattern "Tech Talk"

# Ekskluder episoder som matcher
python3 src/cli.py --source https://example.com/feed.xml \
                   --output filtered.xml \
                   --pattern "Ads|Promo" \
                   --exclude
```

### 2. Berike med Podcasting 2.0 tags
Legg til `<podcast:person>` tags for hosts, guests, etc:

```python
from src.feed_processor import PodcastFeedProcessor

processor = PodcastFeedProcessor("https://example.com/feed.xml")
processor.fetch_feed()
processor.filter_by_title_pattern("My Show")

# Legg til person-informasjon
persons = {
    "episode_guid_123": [
        {"name": "John Doe", "role": "host", "href": "https://example.com/john"}
    ]
}
processor.enrich_with_persons(persons)
processor.generate_feed("output.xml")
```

### 3. Podchaser API-integrasjon
Hent creator-informasjon automatisk:

```python
from src.podchaser_api import PodchaserAPI

api = PodchaserAPI(api_key="your_api_key")
creators = api.enrich_feed_with_creators("My Podcast Name")
# Returns: [{"name": "...", "role": "host", "href": "...", "img": "..."}]
```

## Installasjon

### Med uv (anbefalt)
```bash
# 1. Installer uv hvis du ikke har det
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Opprett virtuelt miljø
uv venv

# 3. Aktiver miljøet
source .venv/bin/activate
# Eller bruk convenience-scriptet:
# source activate.sh

# 4. Installer dependencies
uv pip install -e .

# Med dev-dependencies
uv pip install -e ".[dev]"
```

### Med pip
```bash
# Opprett virtuelt miljø
python3 -m venv .venv
source .venv/bin/activate

# Installer
pip install -e .
```

**Viktig:** På macOS/Linux bruker du `python3` kommandoen (ikke `python`).

## Bruk

### Metode 1: Command-line (enkelt)

```bash
# Grunnleggende filtrering
python3 src/cli.py \
    --source "https://feeds.example.com/podcast.xml" \
    --output "filtered_feed.xml" \
    --pattern "Interesting Topic" \
    --title "My Filtered Podcast"
```

### Metode 2: Config-fil (avansert)

Opprett en `config.yaml` (se `example_config.yaml` for komplett eksempel):

```yaml
feeds:
  - name: "My Favorite Show"
    source_url: "https://example.com/combined-feed.xml"
    output_file: "output/favorite_show.xml"

    filter:
      type: "title_pattern"
      pattern: "My Favorite Show:"
      keep_matching: true

    metadata:
      title: "My Favorite Show - Separated Feed"
      description: "Only episodes from My Favorite Show"

    enrich:
      persons:
        static:
          - name: "Host Name"
            role: "host"
            href: "https://example.com/host"
```

Kjør:
```bash
python3 src/cli.py --config config.yaml
```

### Metode 3: Python API

```python
from src.feed_processor import PodcastFeedProcessor

# Initialize
processor = PodcastFeedProcessor("https://example.com/feed.xml")

# Fetch og parse
processor.fetch_feed()

# Filtrer episoder
processor.filter_by_title_pattern("Tech Talk", keep_matching=True)

# Eller bruk custom filter-funksjon
processor.filter_by_custom_function(
    lambda entry: len(entry.get('title', '')) > 50
)

# Generer ny feed
processor.generate_feed(
    "output.xml",
    feed_title="Filtered Podcast",
    feed_description="My filtered feed"
)
```

## Use Cases

### Use Case 1: Splitt kombinert feed
Noen podcasts publiserer flere shows i samme feed:

```yaml
feeds:
  - name: "Show A Only"
    source_url: "https://network.example.com/all-shows.xml"
    output_file: "show_a.xml"
    filter:
      type: "title_pattern"
      pattern: "^Show A:"
      keep_matching: true

  - name: "Show B Only"
    source_url: "https://network.example.com/all-shows.xml"
    output_file: "show_b.xml"
    filter:
      type: "title_pattern"
      pattern: "^Show B:"
      keep_matching: true
```

### Use Case 2: Berik med creator-info fra Podchaser

```yaml
feeds:
  - name: "My Podcast with Creators"
    source_url: "https://example.com/feed.xml"
    output_file: "enriched.xml"

    enrich:
      persons:
        podchaser:
          enabled: true
          podcast_name: "My Podcast Name"

podchaser:
  api_key: "your_api_key_here"
```

## Konfigurasjon

### Miljøvariabler
- `PODCHASER_API_KEY`: API-nøkkel for Podchaser (valgfritt)

## Struktur

```
podcast-feed-updater/
├── src/
│   ├── feed_processor.py    # Hovedlogikk for feed-prosessering
│   ├── podchaser_api.py     # Podchaser API-klient
│   └── cli.py               # Command-line interface
├── pyproject.toml           # Project dependencies
├── example_config.yaml      # Eksempel-konfigurasjon
└── README.md
```

## Kommende funksjoner

- [ ] Støtte for flere Podcasting 2.0 tags (`<podcast:chapters>`, `<podcast:transcript>`)
- [ ] Webhook-basert auto-oppdatering
- [ ] Web UI for konfigurasjon
- [ ] Docker container
- [ ] Flere API-integrasjoner (Apple Podcasts, Spotify)

## Lisens

MIT

## Bidrag

Pull requests er velkomne! For større endringer, vennligst åpne et issue først.
