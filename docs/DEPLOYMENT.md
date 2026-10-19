# Publisering

Feedene bygges av GitHub Actions og publiseres fra `output/` til `gh-pages`-branchen
(GitHub Pages). Alle workflows kjøres manuelt: Actions → velg workflow → **Run workflow**,
eller `gh workflow run <fil>`.

| Workflow | Gjør |
|----------|------|
| `enrich-feed.yml` | Beriket feed og YouTube-variant for cd SPILL, deretter varsles Podcast Index (`pubnotify.py`) |
| `enrich-feed-spotify.yml` | Spotify-varianten, bygd fra den publiserte feeden |
| `enrich-feed-fallback-test.yml` | Testfeedene uten description, content:encoded eller itunes:summary |
| `build-list-feed.yml` | Tiltcast-listefeedene (bruker Podchaser-poeng) |

Alle deployer med `keep_files: true`, så de overskriver ikke hverandres filer.

## Oppsett for et nytt repo

1. **Settings → Actions → General → Workflow permissions:** Read and write.
2. **Settings → Pages:** Source `gh-pages`, mappe `/ (root)`. Feeden havner på
   `https://<bruker>.github.io/<repo>/<feed>`. Sett denne adressen (uten filnavn) som
   `[publish] base_url`.
3. **Secrets** (bare for listefeeden): `PODCHASER_API_KEY` og `PODCHASER_API_SECRET`.

For en annen podcast: kopier `enrich-feed.yml`, og bytt `--podcast cdspill` og
`cdspill-enriched.xml`. Bruker flere podcaster samme Pages, må de ha ulik `[chapters] publish_path`.

## Feilsøking

- **403 ved deploy:** workflowen mangler skrivetilgang (punkt 1).
- **Feilen kommer bare i CI:** kjør lokalt med `uv run enrich.py --local-cache`, og les loggen i Actions.
- **Valider feeden:** <https://podba.se/validate/>.
