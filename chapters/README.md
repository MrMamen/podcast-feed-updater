# Chapter JSON Files

This directory contains chapter metadata files exported from [mp3chapters.github.io](https://mp3chapters.github.io).

## Purpose

These files provide enhanced chapter data that isn't available from Podbean's auto-generated JSON chapters:

- **Hidden chapters** (`toc: false`) - Chapters excluded from table of contents
- **Chapter URLs** - Links to external resources referenced in chapters
- **Precise timestamps** - Millisecond precision vs Podbean's whole seconds
- **Complete metadata** - All chapter data as defined in the source MP3 file

## Naming Convention

**IMPORTANT:** Files must use the **exact same filename** as Podbean's chapter JSON.

To find the correct filename:
1. Look at Podbean's RSS feed
2. Find the `<podcast:chapters url="...">` tag
3. Extract the filename from the URL

Example:
```xml
<podcast:chapters url="https://mcdn.podbean.com/mf/web/888tat6a7imp5kuy/Outrun_chapters.json" />
```
Save as: `chapters/Outrun_chapters.json` (not `episode_123.json`)

## Format

```json
{
  "version": "1.2.0",
  "chapters": [
    {
      "startTime": 0,
      "title": "Intro"
    },
    {
      "startTime": 2024.502,
      "title": "Vineyard",
      "toc": false
    },
    {
      "startTime": 1944.116,
      "title": "Ulike endings",
      "url": "https://www.vgmuseum.com/end/arcade/c/out.htm"
    }
  ]
}
```

## Workflow

1. **Edit chapters** in [mp3chapters.github.io](https://mp3chapters.github.io)
2. **Export** as "Podcast Namespace JSON (without images)"
3. **Find filename** from Podbean RSS feed's `<podcast:chapters url="...">`
4. **Save** as `chapters/{filename}` (e.g., `chapters/Outrun_chapters.json`)
5. **Commit** the file to the repository
6. **Run enricher** - it will automatically:
   - Load local file instead of fetching from Podbean
   - **Inject episode cover art** for standard chapters (Intro, Dagens spill)
   - Copy enhanced JSON to `docs/chapters/` for GitHub Pages hosting
   - Update `podcast:chapters` URL to point to GitHub Pages
   - Filter out hidden chapters from PSC XML and YouTube timestamps
   - Preserve chapter URLs and precise timestamps

## What Happens During Enrichment

For each episode with chapters:
1. **Check:** Does `chapters/{filename}` exist?
2. **If YES:**
   - Load local JSON file
   - Copy to `docs/chapters/{filename}` (for hosting)
   - Update `<podcast:chapters url="...">` to GitHub Pages URL
   - Generate PSC with hidden chapters filtered out (34 vs 57 for OutRun)
3. **If NO:**
   - Fetch from Podbean (original behavior)
   - No hidden chapter support
   - Rounded timestamps
   - No chapter URLs

## Benefits

### Hidden Chapters Support

Hide detail chapters from the table of contents while keeping them in the MP3 file for ID3-capable players:

- Individual game endings or routes (e.g., "Vineyard", "Death Valley")
- Platform-specific ports (e.g., "C64-port", "Amiga-port")
- Sequels and spin-offs (e.g., "Out Run 3-D", "Turbo Out Run")
- Technical details

**Example:** OutRun episode
- **Source:** 57 total chapters (23 hidden)
- **PSC output:** 34 visible chapters
- **Result:** Clean TOC with detailed info for players that support it

### Enhanced Metadata vs Podbean

| Feature | Local JSON | Podbean JSON |
|---------|-----------|--------------|
| Hidden chapters (`toc: false`) | ✅ 23 chapters | ❌ 0 (stripped) |
| Chapter URLs | ✅ 6 URLs | ❌ 0 (stripped) |
| Timestamp precision | ✅ 41.97s | ❌ 42s (rounded) |
| Hosted URL | ✅ GitHub Pages | ⚠️ Podbean |

### Consistent Experience

Both JSON and PSC chapters now contain the same information:
- Same visible chapters (hidden ones excluded)
- Same chapter URLs
- Same metadata

Apps that only support JSON chapters get the same quality as apps that support PSC.

## Automatic Image Injection

The enricher automatically adds images to standard chapters that don't already have them.

### Current Patterns

**Episode Cover Art** (from episode's `itunes:image`) is automatically injected for:
- **"Intro"** - Episode introduction
- **"Dagens spill: [Game Name]"** - Today's game announcement
- **"Har det holdt seg?"** - "Has it aged well?" evaluation
- **"Kommentarer fra sosiale medier"** - Social media comments

**Podcast Logo** (from channel `itunes:image`) is automatically injected for:
- **"Velkommen til cd SPILL"** - Welcome segment
- Variations: "Velkommen til CD Spill" (case-insensitive)

**Previous Episode Cover Art** (from previous episode's `itunes:image`) is automatically injected for:
- **"Kommentarer fra forrige episode"** - Comments from previous episode
- **"Kommentarer fra sist"** - Comments from last episode

**Next Episode Cover Art** (from next episode's `itunes:image`, if published) is automatically injected for:
- **"Neste episode"** - Next episode preview

### How It Works

1. Enricher builds an index of all episodes with their cover art URLs
2. For the current episode:
   - Reads episode's own cover art (`itunes:image`)
   - Reads podcast logo (channel `itunes:image`)
   - Identifies previous episode's cover art (next in feed)
   - Identifies next episode's cover art (previous in feed, if exists)
3. For each chapter without an `img` field:
   - Checks if title matches a pattern
   - If match: injects appropriate image URL
4. Saves enhanced JSON to `docs/chapters/`
5. PSC chapters in RSS include all images

### Example

**Before (source file):**
```json
{
  "startTime": 0,
  "title": "Intro"
},
{
  "startTime": 41.97,
  "title": "Velkommen til cd SPILL"
},
{
  "startTime": 241.514,
  "title": "Kommentarer fra forrige episode"
}
```

**After (hosted file):**
```json
{
  "startTime": 0,
  "title": "Intro",
  "img": "https://pbcdn1.podbean.com/imglogo/ep-logo/pbblog7653866/OutRun_fjiib8.jpg"
},
{
  "startTime": 41.97,
  "title": "Velkommen til cd SPILL",
  "img": "https://pbcdn1.podbean.com/imglogo/image-logo/7653866/cdSPILL_qsiy74.jpg"
},
{
  "startTime": 241.514,
  "title": "Kommentarer fra forrige episode",
  "img": "https://pbcdn1.podbean.com/imglogo/ep-logo/pbblog7653866/Rainbox6.jpg"
}
```

### Benefits

- ✅ **No manual work** - 7 standard chapters get images automatically
- ✅ **Consistent across episodes** - Same pattern = same image type
- ✅ **Contextual images** - Previous/next episode chapters show correct covers
- ✅ **All Podbean-hosted** - No extra hosting needed
- ✅ **Works everywhere** - JSON chapters, PSC chapters, and podcast apps
- ✅ **Source files stay clean** - No `img` fields needed in `chapters/` directory
- ✅ **Non-destructive** - Existing images are never overwritten

### Coverage

Based on chapter analysis across 56 episodes:
- **"Intro"** (51.8%) → Episode cover ✓
- **"Velkommen til cd SPILL"** (76.8%) → Podcast logo ✓
- **"Dagens spill: [Game]"** (83.9%) → Episode cover ✓
- **"Kommentarer fra forrige episode"** (46.4%) → Previous cover ✓
- **"Kommentarer fra sosiale medier"** (73.2%) → Episode cover ✓
- **"Har det holdt seg?"** (82.1%) → Episode cover ✓
- **"Neste episode"** (51.8%) → Next cover ✓

This covers the most common structural chapters, automatically providing images for approximately 70-80% of each episode's chapters.

## Notes

- **Images:** Chapter images in source files are preserved. Images can also be automatically injected for standard chapters (see Automatic Image Injection above). Images in MP3 ID3 tags remain there for ID3-capable players.
- **Podbean fallback:** Episodes without local chapter files use Podbean's auto-generated JSON (no enhancements, no image injection).
- **File matching:** Enricher extracts filename from podcast:chapters URL and checks if it exists locally.
- **Hosting:** Generated files are in `docs/chapters/` (ignored by git, generated by enricher).
- **Image injection:** Only adds images to chapters that don't already have them - existing images are never overwritten.
