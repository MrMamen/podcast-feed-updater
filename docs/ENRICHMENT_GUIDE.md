# Feed Enrichment Guide

Guide til å berike podcast-feeds med Podcasting 2.0 tags.

## 🎯 Hva er Podcasting 2.0?

Podcasting 2.0 er en samling nye RSS-tags som gjør podcasts mer interaktive og funksjonelle:

- **`<podcast:person>`** - Vis hvem som er hosts og gjester
- **`<podcast:funding>`** - Link til Patreon/støttekanaler
- **`<podcast:chapters>`** - Kapitler med tidskoder (JSON format)
- **`<psc:chapters>`** - Podlove Simple Chapters (inline XML)
- **`<podcast:transcript>`** - Transkripsjoner
- **`<podcast:value>`** - Bitcoin/streaming payments
- **`<podcast:socialInteract>`** - Kommentarer på sosiale medier
- **OP3 Analytics** - Privacy-respecting download tracking

Mer info:
- https://podcastindex.org/namespace/1.0
- https://podlove.org/simple-chapters/

## 📝 Eksempel: cd SPILL

cd SPILL er satt opp i `podcasts/cdspill/podcast.toml`. Andre podcaster settes opp på
samme måte, se [CONFIGURATION.md](CONFIGURATION.md):

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
  <podcast:person role="host" img="..." href="...">Sigve Baar Digernes</podcast:person>
  <podcast:person role="host" img="..." href="...">Erik André Vik Mamen</podcast:person>
  <podcast:funding url="https://www.patreon.com/cdSPILL">
    Støtt cd SPILL på Patreon
  </podcast:funding>
  <podcast:socialInteract protocol="activitypub" uri="..." accountId="..."/>

  <item>
    <title>Total Annihilation med Roar Granevang</title>
    ...
    <!-- NYE TAGS -->
    <podcast:person role="guest" img="..." href="...">Roar Granevang</podcast:person>
  </item>
</channel>
```

## 🚀 Hvordan bruke

### Steg 1: Kjør enrichment-scriptet

```bash
uv run enrich.py                       # --podcast cdspill velges automatisk når den er alene
```

Hva som legges til styres av `podcasts/cdspill/podcast.toml`. For cd SPILL vil det:
- ✅ Legge til permanent hosts fra `podcasts/cdspill/permanent_staff.json`
- ✅ Auto-detektere gjester fra episode-titler ("med [Name]", `[titles]` i podcast.toml)
- ✅ Berike med profil-bilder og URLs fra `podcasts/cdspill/known_guests.json`
- ✅ Legge til funding link (Patreon)
- ✅ Legge til social interact (Bluesky, Twitter/X, Facebook)
- ✅ Legge til season/episode tags (sesongnavn fra `[seasons]`)
- ✅ OP3 analytics for nedlastingssporing
- ✅ Podlove Simple Chapters

### Steg 2: Legg til nye gjester (valgfritt)

Hvis en ny gjest dukker opp og mangler profilbilde:

```bash
# Interaktiv meny (legg til, fyll inn bilde/URL, sync, episode)
uv run guests.py

# Eller direkte:
uv run guests.py add "Guest Name"
uv run guests.py add "Full Name" --alias "Short Name"
uv run guests.py refresh          # fyll inn manglende bilde/URL for alle
```

Dette legger automatisk til gjesten i `podcasts/cdspill/known_guests.json` med profilbilde og Podchaser-URL.

**Se [PERSON_DATA_README.md](PERSON_DATA_README.md)** for fullstendig dokumentasjon av person-data systemet.

## 📊 Resultat

Etter enrichment:

**Channel-nivå:**
- ✅ 2 hosts med profil-bilder og URLs
- ✅ Patreon funding-link
- ✅ Social interactions (Bluesky, Twitter/X, Facebook)
- ✅ OP3 analytics tracking
- ✅ Podcast GUID for portabilitet
- ✅ Update frequency (biweekly)
- ✅ Podroll (anbefalte podcasts)

**Episode-nivå:**
- ✅ Auto-detected guests fra episode-titler
- ✅ Season/episode tags med norske sesongnavn
- ✅ OP3-prefixede enclosure-URLer
- ✅ Podlove Simple Chapters (inline XML format)

**Output:**
- `output/cdspill-enriched.xml` (klar for hosting)
```

## 🌟 Avanserte features

### OP3 Analytics

OP3 (Open Podcast Prefix Project) gir deg gratis nedlastingsstatistikk uten å kompromittere lytternes personvern:

```python
# Legger til OP3-prefix automatisk
enricher.add_op3_prefix()

# Enclosure-URLer blir prefixet (HTTPS-protokoll fjernes for kortere URLer):
# Fra: https://example.com/episode.mp3
# Til:  https://op3.dev/e/example.com/episode.mp3

# HTTP-URLer beholder protokollen:
# Fra: http://example.com/episode.mp3
# Til:  https://op3.dev/e/http://example.com/episode.mp3

# Stats tilgjengelig på:
# https://op3.dev/show/[your-show-guid]
```

**Fordeler:**
- 🆓 Gratis og åpen kildekode
- 🔒 Privacy-respecting (ingen tracking cookies)
- 📊 Industri-standard nedlastingsmetrikk
- 🌍 Offentlig tilgjengelig statistikk

Mer info: https://op3.dev

### Podlove Simple Chapters

Konverterer eksisterende JSON-chapters til Podlove Simple Chapters format for bedre kompatibilitet:

```python
# Konverterer automatisk fra podcast:chapters JSON (Spotify-varianten gjør dette)
enricher.convert_json_chapters_to_psc(base_url="https://example.com/chapters")

# JSON format (podcast:chapters):
# {"chapters": [{"startTime": 0, "title": "Intro"}]}

# Blir til PSC format:
# <psc:chapters version="1.2">
#   <psc:chapter start="00:00:00" title="Intro" />
# </psc:chapters>
```

**Fordeler:**
- ✅ Inline XML (ingen eksterne filer å vedlikeholde)
- ✅ Bedre kompatibilitet med eldre podcast-apper
- ✅ Støtter både JSON og PSC samtidig
- ✅ Automatisk tidskonvertering (sekunder → HH:MM:SS)

**Hva konverteres:**
- Kapittel-titler (title)
- Start-tider (startTime → start)
- Kapittel-URL-er (url → href) - valgfritt
- Kapittel-bilder (img → image) - valgfritt

Mer info: https://podlove.org/simple-chapters/

## 📚 Ressurser

- **Person Data System:** [PERSON_DATA_README.md](PERSON_DATA_README.md)
- **Podchaser API Docs:** https://api-docs.podchaser.com
- **Podcasting 2.0 Spec:** https://github.com/Podcastindex-org/podcast-namespace
- **Podcast Apps som støtter 2.0:** https://podcastindex.org/apps
- **Validator:** https://podba.se/validate/
- **OP3 Analytics:** https://op3.dev
- **Podlove Simple Chapters:** https://podlove.org/simple-chapters/

## 🆘 Feilsøking

### "podcast namespace not found"
**Løsning:** Scriptet legger automatisk til namespace. Hvis det fortsatt feiler, sjekk at lxml er installert:
```bash
uv pip install lxml
```

### Gjester blir ikke funnet
**Løsning:** Gjester detekteres automatisk fra episode-titler med mønsteret i `[titles] guest_pattern`. For cd SPILL er det "med [Name]":
```python
# Eksempel:
# Episode: "Total Annihilation med Roar Granevang (#120)"
# Auto-detekterer: "Roar Granevang"

# Episode: "OutRun med Mats Lindh og Øystein Lill (#53)"
# Auto-detekterer: "Mats Lindh" og "Øystein Lill"
```

Hvis en gjest mangler profilbilde:
```bash
uv run guests.py refresh "Guest Name"
```

### Gjest har feil navn i episode-tittel
**Løsning:** Legg til alias i `podcasts/cdspill/known_guests.json`:
```json
{
  "aliases": {
    "Short Name": "Full Name",
    "Nickname": "Real Name"
  }
}

## 💡 Tips

1. **Start enkelt:** Legg først til hosts, så funding, så gjester
2. **Test lokalt:** Sjekk fila i `output/` før du publiserer
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

---

**Laget med ❤️ for norsk podcast-miljø**
