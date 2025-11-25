# GitHub Actions Workflows

## Enrich cd SPILL Feed

Automatisk workflow som:
1. Kjører `enrich_cdspill.py` hver 6. time
2. Sjekker om feeden har endret seg (smart caching)
3. Genererer beriket feed med Podcasting 2.0 tags
4. Deployer til GitHub Pages

### Triggers

- **Scheduled:** Hver 6. time (00:00, 06:00, 12:00, 18:00 UTC)
- **Manual:** Via Actions tab → "Run workflow"
- **Push:** Automatisk ved push til master (for testing)

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
  # Hver time
  - cron: '0 * * * *'

  # Hver 30. minutt
  - cron: '*/30 * * * *'

  # Hver dag kl 12:00 UTC
  - cron: '0 12 * * *'
```

Se cron syntax: https://crontab.guru/
