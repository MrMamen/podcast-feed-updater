# Rad Crew Feed Splitter Setup

Dette dokumentet forklarer hvordan Rad Crew-feedene er satt opp og hvordan du oppdaterer dem.

## 🎯 Hva gjør dette?

Rad Crew publiserer alle sine podcasts (NEON, Retro Crew, og hovedshowet) i én samlet feed på Soundcloud:
- **Kilde:** https://feed.radcrew.net/radcrew (494 episoder)

Dette scriptet **splitter** denne feeden i tre separate feeds og **beriker** dem med metadata fra de opprinnelige feedene:

### 1. Rad Crew: NEON (135 episoder)
- **Filter:** Tittel inneholder "neon"
- **Metadata fra:** https://feed.radcrew.net/radcrewneon
- **Resultat:** Popkultur-episodene med riktige bilder og beskrivelse

### 2. Retro Crew (18 episoder)
- **Filter:** Tittel inneholder "retro crew"
- **Metadata fra:** https://www.radcrew.net/category/retrocrew/feed
- **Resultat:** Retrogaming-episodene med riktig artwork

### 3. Rad Crew Classic (341 episoder)
- **Filter:** Alt som ikke matcher de to over
- **Metadata fra:** https://www.radcrew.net/category/classic/feed
- **Resultat:** Gaming-hovedshowet med klassisk Rad Crew-metadata

## 🚀 Hvordan oppdatere feedene

Når nye episoder kommer ut:

### Steg 1: Kjør splitter-scriptet
```bash
# Kjør splitter (uv håndterer virtuelt miljø automatisk)
uv run split_radcrew.py
```

Dette vil:
- Hente den nyeste feeden fra Soundcloud
- Splitte den i tre deler
- Berike hver del med metadata
- Generere tre XML-filer i `docs/` mappen

### Steg 2: Last opp til Netlify
1. Gå til https://app.netlify.com/drop
2. Logg inn (hvis nødvendig)
3. Dra `docs/` mappen til Netlify
4. Ferdig! Feedene er oppdatert

## 📡 Feed URLs

Etter opplasting er feedene tilgjengelige på:

- **NEON:** https://radcrew.netlify.app/radcrew-neon.xml
- **Retro Crew:** https://radcrew.netlify.app/radcrew-retro.xml
- **Classic:** https://radcrew.netlify.app/radcrew-classic.xml

## 🔧 Teknisk oversikt

### Arkitektur
```
Soundcloud Feed (494 ep)
         |
         v
   FeedSplitter
    /    |    \
   /     |     \
NEON  Retro  Classic
  |      |      |
  v      v      v
Merge  Merge  Merge
with   with   with
metadata
  |      |      |
  v      v      v
Output XML files
```

### Kode-komponenter

1. **`src/radcrew/splitter.py`**
   - `FeedSplitter`: Splitter feed basert på title-patterns og merger med metadata

2. **`split_radcrew.py`**
   - Kjørbart script som koordinerer hele prosessen
   - Definerer patterns og target-feeds
   - Genererer de tre output-filene

### Filtrering

Filtreringen skjer basert på episode-titler:

```python
patterns = [
    ("neon", True),        # Match "neon" case-insensitive
    ("retro crew", True),  # Match "retro crew" case-insensitive
    # Alt annet går til Classic
]
```

Dette er **regex-patterns**, så du kan bruke avanserte mønstre hvis nødvendig:
- `"neon|weekend crew"` - Match begge alternativer
- `"^NEON #\d+"` - Match kun episoder som starter med "NEON #" fulgt av nummer
- `"retro crew:? "` - Match både "Retro Crew:" og "Retro Crew "

## 🔄 Automatisering (fremtidig)

For å automatisere oppdateringen kan du:

### Alternativ 1: GitHub Actions (anbefalt)
Se `docs/github-actions-example.yml` for et eksempel på hvordan du setter opp automatisk oppdatering hver time.

### Alternativ 2: Cron job på server
```bash
# Legg til i crontab (kjør hver time)
0 * * * * cd /path/to/podcast-feed-updater && ./split_radcrew.py && rsync -av docs/ user@server:/var/www/feeds/
```

### Alternativ 3: Netlify webhook + GitHub
1. Push koden til GitHub
2. Koble Netlify til GitHub repo
3. Sett opp GitHub Action til å kjøre scriptet og commite endringer
4. Netlify auto-deployer når `docs/` endres

## 🐛 Feilsøking

### Problem: "No items found"
**Løsning:** Sjekk at source feed er tilgjengelig:
```bash
curl -I https://feed.radcrew.net/radcrew
```

### Problem: "Namespace issues"
**Løsning:** XML-parseren bevarer alle namespaces. Dette er normalt og feedene vil fungere.

### Problem: "Feed ikke oppdatert i podcast-app"
**Løsning:** Mange apps cacher feeds i 1-24 timer. Vent eller force refresh i appen.

## 📝 Vedlikehold

### Legge til nye kategorier
For å legge til en fjerde kategori (f.eks. "Interviews"):

1. Rediger `split_radcrew.py`:
```python
patterns = [
    ("neon", True),
    ("retro crew", True),
    ("interview", True),  # NY!
    # Rest går til Classic
]

metadata_urls = [
    "https://feed.radcrew.net/radcrewneon",
    "https://www.radcrew.net/category/retrocrew/feed",
    "https://example.com/interviews/feed",  # NY!
    "https://www.radcrew.net/category/classic/feed",
]

output_files = [
    "docs/radcrew-neon.xml",
    "docs/radcrew-retro.xml",
    "docs/radcrew-interviews.xml",  # NY!
    "docs/radcrew-classic.xml",
]
```

2. Kjør scriptet og test

### Endre filter-patterns
Hvis episode-titler endrer format, rediger patterns i `split_radcrew.py`.

## 📚 Ressurser

- [Podcasting 2.0 spec](https://github.com/Podcastindex-org/podcast-namespace)
- [RSS 2.0 spec](https://www.rssboard.org/rss-specification)
- [Apple Podcasts RSS spec](https://podcasters.apple.com/support/823-podcast-requirements)

## 🆘 Support

Hvis du har problemer:
1. Sjekk at alle source feeds er tilgjengelige
2. Sjekk Python-feilmeldinger
3. Test feeds i https://podba.se/validate/ eller https://castfeedvalidator.com/
4. Åpne issue på GitHub
