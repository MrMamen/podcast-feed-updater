# GitHub Actions Workflows

## Enrich cd SPILL Feed

Automatisk workflow som:
1. Kjører `enrich_cdspill.py` hver 6. time
2. Sjekker om feeden har endret seg (smart caching)
3. Genererer beriket feed med Podcasting 2.0 tags
4. Deployer til GitHub Pages

### Triggers

- **Scheduled (Mondays):** Hver time (når nye episoder publiseres)
- **Scheduled (Other days):** Én gang daglig kl. 12:00 UTC (for oppdateringer/rettelser)
- **Manual:** Via Actions tab → "Run workflow"
- **Push:** Automatisk ved push til master (for testing)

**Rasjonale:** cd SPILL publiserer nye episoder på mandager, så workflow sjekker oftere den dagen. Resten av uken sjekkes kun én gang daglig for eventuelle oppdateringer eller rettelser.

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

  # Flere schedules samtidig (som nå)
  - cron: '0 * * * 1'      # Hver time på mandager
  - cron: '0 12 * * 0,2-6' # Daglig kl 12 på søn, tir-lør
```

Se cron syntax: https://crontab.guru/

**Viktig:** Smart caching sørger for at kjøringer uten endringer er raske og billige, så hyppige sjekk koster lite.
