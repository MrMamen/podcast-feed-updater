# Person Data System for cd SPILL

## Overview

Simple, manually maintained system for person data (hosts and guests) with optional Podchaser enrichment.

## Files

### `config/cdspill_permanent_staff.json`
Permanent roles that appear at channel level or across many episodes:
- **Hosts**: Appear on every episode (channel-level tags)
- **Other roles**: Production staff like cover art designers, music composers, etc.

Edit this file directly to add/update permanent staff.

### `config/cdspill_known_guests.json`
Guest data with profile images and URLs:
```json
{
  "guests": {
    "Official Name (from Podchaser)": {
      "img": "https://...",
      "href": "https://www.podchaser.com/creators/..."
    }
  },
  "aliases": {
    "Name in Feed": "Official Name (from Podchaser)"
  }
}
```

**Important**: Guest names in the `guests` object should be the official names from Podchaser.
Names used in episode titles that differ should be added as aliases.

## Workflow

### Option A: Auto-populate all guests (Recommended)

```bash
# 1. Automatically add all guests from episode titles
uv run python3 scripts/guests/populate_guests.py

# This will:
# - Extract all guest names from episode titles
# - Search Podchaser for each new guest
# - Add with profile data if found
# - Add without data if not found
# - Skip guests already in known_guests.json

# 2. Run enricher
uv run enrich_cdspill.py
```

### Option B: Add guest from Podchaser URL

```bash
# Add guest using their Podchaser profile URL
# Interactive menu lets you match with existing guests or add as new
uv run python3 scripts/guests/add_guest_from_url.py "https://www.podchaser.com/creators/name-id"
```

### Option C: Manual per-guest lookup

```bash
# 1. Run enricher to see warnings
uv run enrich_cdspill.py

# 2. Add individual guests
uv run python3 scripts/guests/lookup_guest.py "Guest Name"

# With alias for name variations
uv run python3 scripts/guests/lookup_guest.py "Full Name" --alias "Short Name"

# 3. Re-run enricher
uv run enrich_cdspill.py
```

## Examples

### Auto-populating all guests
```bash
$ uv run python3 scripts/guests/populate_guests.py

============================================================
POPULATE KNOWN GUESTS
============================================================

📦 Currently in config/cdspill_known_guests.json:
   9 guests
   3 aliases
📡 Fetching cd SPILL feed...

🔍 Found 37 unique guests in episode titles

🆕 Found 28 new guests to add:
   - Adrian Haugen
   - Aksel M. Bjerke
   - Anders Ekroll
   ...

🔑 Authenticating with Podchaser...
✓ Authenticated successfully

============================================================
PROCESSING NEW GUESTS
============================================================

[1/28] Adrian Haugen
  ✓ Found profile data
    🔗 URL: ✓
[2/28] Aksel M. Bjerke
  ⚠ Not found in Podchaser
...

============================================================
DONE!
============================================================

✓ Added 28 new guests:
  📷 24 with profile data
  ⚠ 4 without profile data

📊 Total in config/cdspill_known_guests.json:
   37 guests
   3 aliases

💡 Run 'uv run enrich_cdspill.py' to use the updated data
```

### Adding guest from Podchaser URL
```bash
$ uv run python3 scripts/guests/add_guest_from_url.py "https://www.podchaser.com/creators/aleks-gisvold-107tZxOga3"

============================================================
ADD GUEST FROM PODCHASER URL
============================================================

📋 Creator ID: 107tZxOga3
📋 Name from URL: Aleks Gisvold

🔑 Authenticating with Podchaser...
✓ Authenticated
🔍 Searching for 'Aleks Gisvold'...

✓ Found: Aleks Gisvold
  🔗 URL: https://www.podchaser.com/creators/aleks-gisvold-107tZxOga3

🤔 Is 'Aleks Gisvold' the same person as any existing guest?

[?] Select matching guest or add as new:
 > 🔗 Adrian Haugen
   🔗 Aleksander Hakestad
      Aleksikon
   ...
   --- Actions ---
   ➕ Add as new guest (not a match)
   ❌ Cancel

# Use arrow keys to select existing guest or add as new
# If matched with existing:
#   - Podchaser name becomes the official name
#   - Old name (from feed) becomes an alias
#   - Example: "Aleksikon" in feed → "Alexander Gisvold" on Podchaser
#             Result: guests["Alexander Gisvold"], aliases["Aleksikon" → "Alexander Gisvold"]
```

### Getting warnings about missing metadata
```bash
$ uv run enrich_cdspill.py

✓ Auto-detected and added 96 guests from episode titles

  Name normalizations applied:
  'Anette Jøsendal' → 'Anette Vik Jøsendal'

⚠ Found 34 guest(s) without Podchaser URL (href):
  - Adrian Haugen (1 episode)
  - Aksel M. Bjerke (4 episodes)
  - Anders Ekroll (5 episodes)
  - Joachim Froholt (9 episodes)
  ...

💡 Add Podchaser profile with:
   uv run python3 scripts/guests/lookup_guest.py "Guest Name"

💡 If name variations exist, add aliases with:
   uv run python3 scripts/guests/lookup_guest.py "Full Name" --alias "Short Name"
```

**Note:** The enricher only warns about missing Podchaser URLs (href). Profile images (img) are nice to have but not critical.

### Adding a new guest
```bash
$ uv run python3 scripts/guests/lookup_guest.py "Mats Lindh"

🔍 Searching Podchaser for: Mats Lindh
============================================================
Query cost: 7
Points remaining: 12621

✓ Found 1 result(s):

1. Mats Lindh
   Image: ✓
   URL: https://www.podchaser.com/creators/mats-lindh-...

Auto-selecting the only result...

✓ Added to config/cdspill_known_guests.json:
   Name: Mats Lindh
   Image: ✓
   Profile: https://www.podchaser.com/creators/mats-lindh-...

Next: Run 'uv run enrich_cdspill.py' to use the new guest data
```

### Adding with alias
```bash
$ uv run python3 scripts/guests/lookup_guest.py "Jan Anders Ekroll" --alias "Anders Ekroll"

✓ Adding alias: 'Anders Ekroll' → 'Jan Anders Ekroll'
```

Now episode titles with "med Anders Ekroll" will match "Jan Anders Ekroll" and get his profile data.

## Podchaser API Usage

**populate_guests.py cost**: ~7-10 points per new guest found
**lookup_guest.py cost**: ~7-10 points per lookup
**enrich_cdspill.py cost**: 0 points (no API calls)

The enricher runs offline using the JSON files. Podchaser is only used when adding new guests.

## Manual Editing

You can also manually edit `config/cdspill_known_guests.json`:

```json
{
  "guests": {
    "New Guest": {
      "img": "https://creator-images.podchaser.com/hash.jpeg",
      "href": "https://www.podchaser.com/creators/new-guest-id"
    }
  },
  "aliases": {
    "Nickname": "New Guest"
  }
}
```

## Auto-detection

Guests are auto-detected from episode titles using the pattern:
- "med Guest Name" → detects "Guest Name"
- "med Guest1 og Guest2" → detects both guests
- Episode numbers are automatically stripped

### Manual Episode Assignment (extra_episodes)

For guests not mentioned in episode titles, use `extra_episodes` with GUID-based identification:

```json
{
  "guests": {
    "Guest Name": {
      "href": "https://www.podchaser.com/creators/...",
      "img": "https://creator-images.podchaser.com/...",
      "extra_episodes": [
        {
          "guid": "cdspill.podbean.com/053d7b0f-64f8-3a89-88cf-5ec2a8e6f95c",
          "note": "Spillåret 1994 (#106)"
        }
      ]
    }
  }
}
```

**Finding the GUID:**
```bash
# Search feed for episode title
curl -s https://feed.podbean.com/cdspill/feed.xml | grep -A 5 "Episode Title"
# Look for the <guid> tag, e.g.: cdspill.podbean.com/053d7b0f-64f8-3a89-88cf-5ec2a8e6f95c
```

The `note` field is optional but recommended for human readability. GUIDs are stable identifiers that won't change even if episode titles are modified.

### Detecting Missing Aliases

The enricher helps you identify when aliases are needed. If a guest appears in titles with a different name than in `known_guests`, you'll see:

```
⚠ Found 1 guest(s) without Podchaser URL (href):
  - Anette Vik Jøsendal (6 episodes)
    (detected as 'Anette Jøsendal' in titles)
```

This tells you that:
1. Episodes use "Anette Jøsendal" in titles
2. But the official name in known_guests is "Anette Vik Jøsendal"
3. An alias exists: `"Anette Jøsendal": "Anette Vik Jøsendal"`
4. But the official entry is missing href

To fix: Use `add_guest_from_url.py` with the Podchaser URL to add the href.

The enricher only warns about missing Podchaser URLs (href attribute), not missing images.

## Current Status

**Permanent hosts**: 2 (Sigve, Mamen)
**Known guests**: 9 with profile images
**Aliases**: 3 name normalizations

Run `uv run enrich_cdspill.py` to see current counts.
