# GitHub Actions Workflows

## Enrich cd SPILL Feed

Automatisk workflow som:
1. Kjører `enrich_cdspill.py` på mandager
2. Sjekker om feeden har endret seg (smart caching)
3. Genererer beriket feed med Podcasting 2.0 tags
4. Deployer til GitHub Pages

### Triggers

- **Scheduled (Mondays only):** Kl. 07:00, 09:00, 11:00, og 13:00 UTC
- **Manual:** Via Actions tab → "Run workflow" (med valgfri `--force` parameter)
- **Push:** Automatisk ved push til master (for testing)

**Rasjonale:** cd SPILL publiserer nye episoder på mandager, så workflow kjører kun den dagen med 4 kjøringer fordelt utover dagen.

### Output

Enriched feed publiseres til:
```
https://[username].github.io/podcast-feed-updater/cdspill-enriched.xml
```

### Secrets (Valgfritt)

For Podchaser API support, legg til i repository secrets:
- `PODCHASER_API_KEY`
- `PODCHASER_API_SECRET`

Hvis secrets ikke er satt, bruker workflow manuell host-data (fungerer fint).

### Manual Trigger med Force Flag

Når du kjører workflow manuelt kan du velge om du vil tvinge regenerering:

**Via GitHub web:**
1. Gå til Actions tab
2. Velg "Enrich cd SPILL Feed"
3. Klikk "Run workflow"
4. Velg "Force regeneration (ignore cache)":
   - **false** (default): Bruker smart caching, hopper over hvis ingen endringer
   - **true**: Tvinger regenerering selv om ingen endringer er detektert

**Via GitHub CLI:**
```bash
# Normal kjøring med smart caching
gh workflow run enrich-feed.yml

# Med --force flag
gh workflow run enrich-feed.yml -f force=true
```

### Overvåkning

Se workflow status og logs:
- **Actions tab:** https://github.com/[username]/podcast-feed-updater/actions
- **E-postvarsler:** GitHub sender automatisk e-post ved failures

### Customization

Endre kjørefrekvens i `enrich-feed.yml`:

```yaml
schedule:
  # Hver time hele uken
  - cron: '0 * * * *'

  # Hver 30. minutt hele uken
  - cron: '*/30 * * * *'

  # Hver dag kl 12:00 UTC
  - cron: '0 12 * * *'

  # Kun på hverdager kl 08:00 UTC
  - cron: '0 8 * * 1-5'

  # Nåværende oppsett
  - cron: '0 7,9,11,13 * * 1'  # Mandager kl 07:00, 09:00, 11:00, 13:00 UTC
```

Se cron syntax: https://crontab.guru/

**Viktig:** Smart caching sørger for at kjøringer uten endringer er raske og billige, så hyppige sjekk koster lite.
