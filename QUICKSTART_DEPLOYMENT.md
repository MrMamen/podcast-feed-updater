# Quick Start: Deploy til GitHub Pages

5-minutters guide for å få automatisk feed enrichment i produksjon.

## 🚀 Steg 1: Push til GitHub

```bash
# Hvis du ikke har GitHub repo enda:
gh repo create podcast-feed-updater --public --source=. --remote=origin

# Push koden
git add .
git commit -m "Add GitHub Actions deployment workflow"
git push -u origin master
```

## 🔧 Steg 2: Gi GitHub Actions write-tilgang

1. Gå til repository på GitHub
2. Klikk **Settings** → **Actions** → **General** (venstre meny)
3. Scroll ned til **Workflow permissions**
4. Velg **Read and write permissions**
5. Kryss av **Allow GitHub Actions to create and approve pull requests**
6. Klikk **Save**

## 🔧 Steg 3: Aktiver GitHub Pages

1. Fortsatt i **Settings**, klikk **Pages** (venstre meny)
2. Under **Source**:
   - Branch: `gh-pages` (vil bli opprettet automatisk første gang)
   - Folder: `/ (root)`
3. Klikk **Save**

## ▶️ Steg 4: Kjør første deploy

1. Gå til **Actions** tab (øverst)
2. Klikk på workflow "Enrich cd SPILL Feed"
3. Klikk **Run workflow** (høyre side)
4. Klikk den grønne **Run workflow** knappen
5. Vent 1-2 minutter

## ✅ Steg 5: Verifiser at det fungerer

Din berikede feed er nå tilgjengelig på:
```
https://[ditt-github-brukernavn].github.io/podcast-feed-updater/cdspill-enriched.xml
```

Test i nettleser eller valider på: https://podba.se/validate/

## 🎉 Ferdig!

Feeden din oppdateres nå automatisk:
- **Mandager:** Hver time (når nye episoder publiseres)
- **Resten av uken:** Daglig kl. 12:00 UTC

---

## 📋 Valgfritt: Legg til Podchaser API

Hvis du vil bruke Podchaser API for å hente host-info:

1. Gå til **Settings** → **Secrets and variables** → **Actions**
2. Klikk **New repository secret**
3. Legg til:
   - Name: `PODCHASER_API_KEY`
   - Secret: [din API key fra https://www.podchaser.com/api]
4. Gjenta for `PODCHASER_API_SECRET`

Uten disse secrets bruker scriptet manuell host-data (fungerer fint!).

---

## 📋 Valgfritt: Fjern "(Beta)" fra tittel

Når du er klar for produksjon:

1. Åpne `enrich_cdspill.py`
2. Finn linjen:
   ```python
   enricher.set_beta_title(" (Beta)")
   ```
3. Kommenter den ut:
   ```python
   # enricher.set_beta_title(" (Beta)")
   ```
4. Commit og push:
   ```bash
   git add enrich_cdspill.py
   git commit -m "Remove beta suffix for production"
   git push
   ```

Eller la workflow gjøre det automatisk (allerede konfigurert).

---

## 🔄 Manuell kjøring

Når som helst kan du trigge en ny kjøring:
1. Gå til **Actions** tab
2. Velg "Enrich cd SPILL Feed"
3. Klikk **Run workflow**

---

## 📊 Overvåkning

Se status på alle kjøringer:
```
https://github.com/[username]/podcast-feed-updater/actions
```

GitHub sender e-post automatisk hvis noe feiler.

---

## 🆘 Troubleshooting

### Permission denied (403) feil
**Løsning:**
1. Gå til **Settings** → **Actions** → **General**
2. Velg **Read and write permissions**
3. Kryss av **Allow GitHub Actions to create and approve pull requests**
4. Klikk **Save**
5. Re-run workflow

### "gh-pages branch not found"
- Det er normalt første gang
- Workflow oppretter den automatisk ved første kjøring
- Refresh Pages settings etter første kjøring

### Workflow feiler
- Sjekk logs i Actions tab
- Test lokalt først: `uv run enrich_cdspill.py`
- Åpne issue hvis du trenger hjelp

### Feed ikke tilgjengelig
- Vent 2-3 minutter etter første deploy
- Sjekk at GitHub Pages er aktivert
- Force refresh i nettleser (Ctrl+F5)

---

## 💡 Neste steg

Når det fungerer, kan du:
- ✅ Dele feed-URL med lyttere
- ✅ Submit til podcast directories
- ✅ Legge til custom domain (f.eks. `feed.cdspill.no`)
- ✅ Sette opp UptimeRobot for monitoring

Se **DEPLOYMENT.md** for mer avanserte opsjoner.
