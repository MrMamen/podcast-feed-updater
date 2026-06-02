# Tiltcast list feeds

Self-updating RSS feeds built from the Podchaser list
**[Episoder fra Tiltcast i Oslo](https://www.podchaser.com/lists/episoder-fra-tiltcast-i-oslo-11SK7Mk5jl)**.

Podchaser only offers a *static* RSS download of a list. This builder queries
the list via the Podchaser GraphQL API and regenerates feeds on demand, so they
stay in sync when the list changes — and adds proper Podcasting 2.0 metadata.

It produces:

| File | Contents |
|------|----------|
| `tiltcast-all.xml` | All episodes; each edition is a named `<podcast:season>` |
| `tiltcast-1.xml` … `tiltcast-N.xml` | One feed per edition/section, in list order |

Published to GitHub Pages, e.g. `https://mrmamen.github.io/podcast-feed-updater/tiltcast-all.xml`.

> **Unlike `enrich_cdspill.py`**, this does *not* mutate an existing feed. It
> generates feeds from scratch and aggregates episodes from many different
> podcasts (Spillmatic, LOLbua, cd SPILL, NerdCast, …) into one feed.

---

## Running it

**Locally** (uses keys from `.env`):

```bash
uv run build_list_feed.py
```

Writes `tiltcast-*.xml` and copies cover images into `output/` (gitignored).

**On GitHub** (manual): Actions → **Build Tiltcast List Feed** → Run workflow
(`gh workflow run "Build Tiltcast List Feed"`). Requires the repo secrets
`PODCHASER_API_KEY` / `PODCHASER_API_SECRET` (set once in Settings → Secrets →
Actions). Deploys with `keep_files: true`, so the cd SPILL feeds are never
touched.

---

## ⭐ Adding a new edition (e.g. Tiltcast 6.0) — no code change needed

Sections are **not** hardcoded — they come from the list itself. To add 6.0:

1. On Podchaser, add a new **section heading** (`ListHeading`) + the episodes to
   the list, as usual.
2. Drop a cover image at `assets/tiltcast/tiltcast-6.{jpg|png}`
   (**square, 1400–3000 px, RGB** — Apple rejects anything smaller or
   non-square).
3. Re-run the build (locally or via the workflow).

A 6th section automatically produces `tiltcast-6.xml`, and a new season appears
in `tiltcast-all.xml`. Editions map to feeds **by their order in the list**:
section 1 → `tiltcast-1.xml`, etc. The feed *title* is the section heading
verbatim (e.g. `TILTcast 6.0 (...)`).

If the cover file is missing, the feed still builds — it just omits the channel
image and prints a warning.

---

## Things that are easy to forget

- **List id is the numeric internal id, NOT the URL hashid.** The list is
  `1959319` (in `config/tiltcast_list.json`). The `...-11SK7Mk5jl` tail in the
  URL is a hashid that resolves a *different* list if passed to the API. If the
  id ever needs re-resolving, clear `list_id` in the config and the builder
  falls back to searching by `list_search_term`.
- **Audio URLs are kept verbatim.** Source op3 prefixes (cd SPILL) are
  preserved; no op3 is added to the others. Don't "normalize" `audioUrl`.
- **Cost / budget.** Podchaser bills query *points* (~18 per episode + overhead;
  budget is 25 000/month). The builder first runs a cheap count query, then
  checks the full query's cost via the **free** `/graphql/cost` endpoint
  (`PodchaserAPI.estimate_cost`) and **aborts** if running it would drop the
  balance below `min_remaining` (default 12 000 in the config). It logs
  remaining points throughout. A full rebuild of ~28 episodes ≈ 700 points.
  Run it manually/occasionally — don't put it on `push`.
- **Sections = `ListHeading` items**, interleaved in the item stream and ordered
  by `position`. There is no native "sections" field. See
  `src/listfeed/podchaser_list.py`.
- **Episode ordering.** Items follow the curated `position` order (oldest
  edition first). Most podcast apps re-sort by `pubDate` anyway.

---

## File map

| File | Role |
|------|------|
| `build_list_feed.py` | Entry point / orchestration |
| `config/tiltcast_list.json` | List id, search term, language, category, base URL, point floor |
| `src/listfeed/podchaser_list.py` | Fetch + structure the list into sections (cost guard, point logging) |
| `src/listfeed/feed_builder.py` | Build the RSS XML (lxml) — channel + items + seasons |
| `src/enrichment/podchaser_api.py` | Podchaser client; `estimate_cost()` = free `/cost` check |
| `assets/tiltcast/` | Cover art (`tiltcast-all` + `tiltcast-1..N`), square ≥1400 px |
| `.github/workflows/build-list-feed.yml` | Manual workflow → builds + deploys to gh-pages |

## Config (`config/tiltcast_list.json`)

| Key | Meaning |
|-----|---------|
| `list_id` | Numeric Podchaser list id (`1959319`). Empty → resolve via search. |
| `list_search_term` | Fallback search term used when `list_id` is empty. |
| `language` / `author` / `explicit` | Channel metadata. |
| `category` | iTunes category `{text, sub}` (Leisure › Video Games). |
| `base_url` | Public host for feeds + cover images (GitHub Pages). |
| `min_remaining` | Abort if a fetch would leave fewer than this many points. |
| `combined` | `{slug, title}` for the all-editions feed. |
