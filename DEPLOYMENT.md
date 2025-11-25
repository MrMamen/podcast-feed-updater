# Deployment Guide - Automatisk Feed Enrichment

Guide for å sette opp automatisk kjøring og hosting av den berikede feeden.

## 🎯 Anbefalt løsning: GitHub Actions + GitHub Pages

### Fordeler:
- ✅ Helt gratis
- ✅ Automatisk kjøring hver 6. time
- ✅ Gratis hosting via GitHub Pages
- ✅ Smart caching (kjører kun ved endringer)
- ✅ Manuell trigger tilgjengelig
- ✅ Versjonskontroll og historikk

---

## 📋 Oppsett (Steg-for-steg)

### 1. Push koden til GitHub

```bash
# Hvis du ikke allerede har et GitHub repo:
gh repo create podcast-feed-updater --public --source=. --remote=origin --push

# Eller hvis du allerede har repo:
git push origin master
```

### 2. Gi GitHub Actions write-tilgang

GitHub Actions trenger tillatelse til å pushe til repo og deploye til Pages:

1. Gå til repository **Settings**
2. Klikk **Actions** → **General** (venstre meny)
3. Scroll ned til **Workflow permissions**
4. Velg **Read and write permissions**
5. Kryss av **Allow GitHub Actions to create and approve pull requests**
6. Klikk **Save**

### 3. Aktiver GitHub Pages

1. Fortsatt i **Settings**, naviger til **Pages** (venstre meny)
2. Under **Source**, velg:
   - Branch: `gh-pages`
   - Folder: `/ (root)`
3. Klikk **Save**

Din feed vil være tilgjengelig på:
```
https://[ditt-github-brukernavn].github.io/podcast-feed-updater/cdspill-enriched.xml
```

### 4. Legg til Podchaser API secrets (Valgfritt)

Hvis du vil bruke Podchaser API:

1. Gå til repository **Settings** → **Secrets and variables** → **Actions**
2. Klikk **New repository secret**
3. Legg til:
   - Name: `PODCHASER_API_KEY`
   - Value: [din API key]
4. Klikk **Add secret**
5. Gjenta for:
   - Name: `PODCHASER_API_SECRET`
   - Value: [din API secret]

### 5. Fjern Beta-suffix (Produksjon)

Rediger `enrich_cdspill.py` og kommenter ut beta-suffixet:

```python
# enricher.set_beta_title(" (Beta)")  # Deaktivert for produksjon
```

Eller workflow-filen gjør dette automatisk.

### 6. Test workflow

1. Gå til **Actions** tab i GitHub
2. Velg "Enrich cd SPILL Feed"
3. Klikk **Run workflow** → **Run workflow**
4. Vent på at jobben er ferdig (ca. 1-2 min)
5. Sjekk at feeden er tilgjengelig på GitHub Pages URL

---

## ⏰ Kjøreplan

Workflow kjører automatisk:
- **Mandager:** Hver time (når nye episoder publiseres)
- **Resten av uken:** Én gang daglig kl. 12:00 UTC (for oppdateringer/rettelser)
- **Ved push til master** (for testing)
- **Manuelt** (via Actions tab)

**Rasjonale:** cd SPILL publiserer nye episoder på mandager, så workflow sjekker oftere den dagen for rask oppdatering. Resten av uken sjekkes kun én gang daglig for eventuelle rettelser eller oppdateringer.

**Smart caching:** Scriptet sjekker om feeden har endret seg (pubDate + link) og hopper over regenerering hvis ingen endringer. Dette gjør hyppige kjøringer billige og raske.

---

## 🔄 Alternative løsninger

### 2. Netlify (Også gratis)

**Fordeler:**
- ✅ Gratis hosting
- ✅ Automatisk HTTPS
- ✅ Custom domain støtte
- ✅ Build hooks for triggering

**Oppsett:**

1. Opprett `netlify.toml`:

```toml
[build]
  command = "uv run enrich_cdspill.py"
  publish = "docs"

[[redirects]]
  from = "/"
  to = "/cdspill-enriched.xml"
  status = 200
```

2. Koble GitHub repo til Netlify
3. Sett opp **Build hooks** for periodisk kjøring (krever ekstern cron service)

**Feed URL:**
```
https://[your-site].netlify.app/cdspill-enriched.xml
```

### 3. Cloudflare Pages + Workers (Gratis)

**Fordeler:**
- ✅ Gratis hosting
- ✅ Raskere global distribusjon (CDN)
- ✅ Scheduled Workers for cron

**Oppsett:**
- Similar til Netlify, men med Cloudflare Pages
- Bruk Cloudflare Workers Cron Triggers for scheduling

### 4. Egen server (VPS/Docker)

**Fordeler:**
- ✅ Full kontroll
- ✅ Kan kjøre oftere enn hver 6. time

**Oppsett:**

1. Sett opp cron job:

```bash
# Rediger crontab
crontab -e

# Kjør hver time
0 * * * * cd /path/to/podcast-feed-updater && /usr/local/bin/uv run enrich_cdspill.py

# Kjør hver 15. minutt
*/15 * * * * cd /path/to/podcast-feed-updater && /usr/local/bin/uv run enrich_cdspill.py
```

2. Serve feeden med nginx/Apache/Caddy

---

## 📊 Overvåkning

### GitHub Actions

Se workflow status:
```
https://github.com/[username]/podcast-feed-updater/actions
```

### E-postvarsler

GitHub sender automatisk e-post ved workflow failures.

### Feed validering

Valider feeden regelmessig:
- https://podba.se/validate/
- https://castfeedvalidator.com/

---

## 🔧 Feilsøking

### Permission denied (403) feil

**Feilmelding:**
```
remote: Permission to [repo].git denied to github-actions[bot].
fatal: unable to access 'https://github.com/[user]/[repo].git/': The requested URL returned error: 403
```

**Løsning:**
1. Gå til **Settings** → **Actions** → **General**
2. Under **Workflow permissions**, velg **Read and write permissions**
3. Kryss av **Allow GitHub Actions to create and approve pull requests**
4. Klikk **Save**
5. Re-run workflow

### Workflow feiler

1. Sjekk **Actions** tab for error logs
2. Test lokalt først: `uv run enrich_cdspill.py`
3. Sjekk at alle dependencies er i `pyproject.toml`
4. Verifiser at workflow har `permissions: contents: write`

### GitHub Pages ikke tilgjengelig

1. Sjekk at `gh-pages` branch eksisterer
2. Sjekk at GitHub Pages er aktivert i Settings
3. Vent 2-3 minutter etter første deploy
4. Verifiser at Source er satt til `gh-pages` branch

### Smart caching ikke fungerer

1. Sjekk at `.feed_cache/cdspill-enriched.xml.json` blir committed
2. Bruk `--force` flag for å tvinge regenerering

---

## 🎯 Anbefaling for cd SPILL

**Bruk GitHub Actions + GitHub Pages fordi:**

1. **Gratis** - Ingen kostnader
2. **Pålitelig** - GitHub infrastruktur
3. **Enkelt** - Alt er allerede satt opp i `.github/workflows/`
4. **Smart** - Caching reduserer unødvendig prosessering
5. **Transparent** - Se historikk og logs i Actions tab

**URL du kan bruke:**
```
https://[ditt-github-brukernavn].github.io/podcast-feed-updater/cdspill-enriched.xml
```

Denne kan du:
- Legge inn i podcast directories
- Dele med lyttere
- Bruke som "offisiell" feed med alle enrichments

---

## 📝 Neste steg

1. ✅ Push koden til GitHub
2. ✅ Aktiver GitHub Pages
3. ✅ Test workflow manuelt
4. ✅ Verifiser feed på GitHub Pages URL
5. ✅ Valider feeden på podba.se
6. ✅ (Valgfritt) Legg til custom domain
7. ✅ (Valgfritt) Submit til podcast directories

---

## 💡 Tips

- **Custom domain:** Kan legge til via GitHub Pages settings (f.eks. `podcast.cdspill.no`)
- **Kjøre oftere:** Endre cron schedule i workflow (men 6 timer er nok for de fleste)
- **Monitoring:** Sett opp UptimeRobot for å overvåke feed-tilgjengelighet
- **Backup:** GitHub Pages history fungerer som backup

---

## 🆘 Hjelp

Hvis du støter på problemer:
1. Sjekk GitHub Actions logs
2. Test lokalt: `uv run enrich_cdspill.py --force`
3. Valider XML: `xmllint --noout docs/cdspill-enriched.xml`
4. Åpne issue i repo eller spør i Podcasting 2.0 community
