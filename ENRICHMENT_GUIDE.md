# Feed Enrichment Guide

Guide til å berike podcast-feeds med Podcasting 2.0 tags.

## 🎯 Hva er Podcasting 2.0?

Podcasting 2.0 er en samling nye RSS-tags som gjør podcasts mer interaktive og funksjonelle:

- **`<podcast:person>`** - Vis hvem som er hosts og gjester
- **`<podcast:funding>`** - Link til Patreon/støttekanaler
- **`<podcast:chapters>`** - Kapitler med tidskoder
- **`<podcast:transcript>`** - Transkripsjoner
- **`<podcast:value>`** - Bitcoin/streaming payments
- **`<podcast:socialInteract>`** - Kommentarer på sosiale medier

Mer info: https://podcastindex.org/namespace/1.0

## 📝 Eksempel: cd SPILL

Vi har laget et komplett eksempel for cd SPILL-podcasten:

### Før:
```xml
<channel>
  <title>cd SPILL</title>
  <itunes:author>C:\SPILL＞</itunes:author>
  ...
  <item>
    <title>Total Annihilation med Roar Granevang</title>
    ...
  </item>
</channel>
```

### Etter enrichment:
```xml
<channel>
  <title>cd SPILL</title>
  <itunes:author>C:\SPILL＞</itunes:author>

  <!-- NYE TAGS -->
  <podcast:person role="host" href="...">Sigve Indregard</podcast:person>
  <podcast:person role="host" href="...">Hans-Henrik Mamen</podcast:person>
  <podcast:funding url="https://www.patreon.com/cdSPILL">
    Støtt cd SPILL på Patreon
  </podcast:funding>
  <podcast:socialInteract protocol="activitypub" uri="..." accountId="..."/>

  <item>
    <title>Total Annihilation med Roar Granevang</title>
    ...
    <!-- NYE TAGS -->
    <podcast:person role="guest" href="...">Roar Granevang</podcast:person>
  </item>
</channel>
```

## 🚀 Hvordan bruke

### Metode 1: Automatisk via Podchaser API (anbefalt)

```bash
# 1. Få en API-nøkkel fra Podchaser
# Registrer deg på: https://www.podchaser.com/api

# 2. Sett API-nøkkelen som miljøvariabel
export PODCHASER_API_KEY='your_key_here'

# 3. Kjør enrichment-scriptet
uv run python3 enrich_cdspill.py
```

Dette vil:
- ✅ Hente hosts automatisk fra Podchaser
- ✅ Finne gjester basert på episode-titler ("med [Name]")
- ✅ Legge til funding link (Patreon)
- ✅ Legge til social interact (Bluesky)

### Metode 2: Manuell konfigurasjon

Hvis du ikke har Podchaser API-nøkkel, eller vil ha mer kontroll:

```python
# enrich_cdspill.py

hosts = [
    {
        "name": "Your Name",
        "role": "host",
        "href": "https://example.com/yourprofile",
        "img": "https://example.com/yourphoto.jpg"  # Valgfritt
    }
]

episode_guests = {
    "med John Doe": [{  # Matcher episode-titler som inneholder dette
        "name": "John Doe",
        "role": "guest",
        "href": "https://example.com/john"
    }]
}
```

## 📊 Resultat

Etter enrichment:

**Channel-nivå:**
- ✅ 2 hosts med profil-linker
- ✅ Patreon funding-link
- ✅ Bluesky social interaction

**Episode-nivå:**
- ✅ 11 episoder med gjeste-informasjon
- ✅ Automatisk matching basert på episode-tittel

**Output:**
- `docs/cdspill-enriched.xml` (klar for hosting)

## 🔧 Tilpass for din podcast

### 1. Kopier og tilpass scriptet

```bash
cp enrich_cdspill.py enrich_yourpodcast.py
```

### 2. Endre feed-URL og informasjon

```python
# I enrich_yourpodcast.py

enricher = FeedEnricher("https://your-feed-url.com/feed.xml")

hosts = [
    {"name": "Your Host", "role": "host", ...}
]

enricher.add_funding(
    url="https://your-patreon-url",
    message="Support us"
)
```

### 3. Legg til gjeste-matching

```python
episode_guests = {
    "Episode #123": [{
        "name": "Guest Name",
        "role": "guest"
    }],
    # Eller match på mønster:
    "with": [{  # Matcher alle episoder med "with" i tittelen
        "name": "Regular Guest",
        "role": "guest"
    }]
}
```

## 🌟 Avanserte features

### Legge til flere Podcasting 2.0 tags

Du kan enkelt utvide `FeedEnricher`-klassen:

```python
# I src/feed_enricher.py

def add_value_tag(self, ...):
    """Add podcast:value for Bitcoin payments"""

def add_transcript(self, url: str, type: str = "text/vtt"):
    """Add podcast:transcript"""

def add_location(self, geo: str, osm: str):
    """Add podcast:location"""
```

### Hente gjester fra andre kilder

```python
# Integrer med andre APIs
from your_api import get_episode_guests

for episode in episodes:
    guests = get_episode_guests(episode.id)
    enricher.add_episode_persons({
        episode.title: guests
    })
```

## 📚 Ressurser

- **Podchaser API Docs:** https://api-docs.podchaser.com
- **Podcasting 2.0 Spec:** https://github.com/Podcastindex-org/podcast-namespace
- **Podcast Apps som støtter 2.0:** https://podcastindex.org/apps
- **Validator:** https://podba.se/validate/

## 🆘 Feilsøking

### "No PODCHASER_API_KEY"
**Løsning:** Sett miljøvariabelen:
```bash
export PODCHASER_API_KEY='your_key'
```

Eller bruk manuell konfigurasjon (scriptet fortsetter automatisk).

### "podcast namespace not found"
**Løsning:** Scriptet legger automatisk til namespace. Hvis det fortsatt feiler, sjekk at lxml er installert:
```bash
uv pip install lxml
```

### Gjester blir ikke funnet
**Løsning:** Sjekk episode_guests-mappingen. Nøkkelen må matche deler av episode-tittelen:
```python
# Eksempel:
# Episode: "Total Annihilation med Roar Granevang (#120)"
# Mapping:
"med Roar": [...]  # ✅ Matcher
"Roar Granevang": [...]  # ✅ Matcher
"Episode 120": [...]  # ❌ Matcher ikke (ikke i tittelen)
```

## 💡 Tips

1. **Start enkelt:** Legg først til hosts, så funding, så gjester
2. **Test lokalt:** Sjekk `docs/`-filen før du publiserer
3. **Valider:** Bruk https://podba.se/validate/ til å sjekke at XML er riktig
4. **Iterer:** Legg til flere gjester over tid etter hvert som du finner dem
5. **Podchaser:** Oppdater din Podchaser-side - det hjelper andre også!

## 🎁 Fordeler med Podcasting 2.0

**For lyttere:**
- 🔍 Søk etter episoder med spesifikke gjester
- 💰 Enkelt å støtte via in-app donations
- 📝 Les transkripsjoner (tilgjengelighet)
- 🗨️ Kommenter direkte fra podcast-appen
- ⏩ Hopp mellom kapitler

**For podcasters:**
- 📈 Bedre søkbarhet
- 💸 Flere støttekanaler
- 🌐 Bredere distribusjon
- 🎨 Rikere metadata
- 🤝 Krediter alle som bidrar

## 🚦 Neste steg

1. ✅ Kjør `enrich_cdspill.py` og test resultatet
2. ✅ Last opp `docs/cdspill-enriched.xml` til Netlify
3. ✅ Test i en Podcasting 2.0-app (f.eks. Fountain, Podverse)
4. ✅ Legg til flere gjester over tid
5. ✅ Vurder andre tags (chapters, transcripts, value)

---

**Laget med ❤️ for norsk podcast-miljø**
