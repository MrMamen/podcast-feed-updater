# GitHub Actions Workflows

## Enrich cd SPILL Feed

Workflow som:
1. Kjører `enrich_cdspill.py` når manuelt triggeret
2. Genererer beriket feed med Podcasting 2.0 tags
3. Deployer til GitHub Pages

### Triggers

- **Manual:** Via Actions tab → "Run workflow"
- **Push:** Automatisk ved push til master branch

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

### Manual Trigger

**Via GitHub web:**
1. Gå til Actions tab
2. Velg "Enrich cd SPILL Feed"
3. Klikk "Run workflow"

**Via GitHub CLI:**
```bash
gh workflow run enrich-feed.yml
```

### Overvåkning

Se workflow status og logs:
- **Actions tab:** https://github.com/[username]/podcast-feed-updater/actions
- **E-postvarsler:** GitHub sender e-post ved failures
