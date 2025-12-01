# Person Data System for cd SPILL

## Overview

Simple, manually maintained system for person data (hosts and guests) with optional Podchaser enrichment.

## Files

### `cdspill_permanent_staff.json`
Permanent roles that appear at channel level or across many episodes:
- **Hosts**: Appear on every episode (channel-level tags)
- **Other roles**: Production staff like cover art designers, music composers, etc.

Edit this file directly to add/update permanent staff.

### `cdspill_known_guests.json`
Guest data with profile images and URLs:
```json
{
  "guests": {
    "Guest Name": {
      "img": "https://...",
      "href": "https://www.podchaser.com/creators/..."
    }
  },
  "aliases": {
    "Short Name": "Full Name"
  }
}
```

## Workflow

### 1. Run enricher normally
```bash
uv run enrich_cdspill.py
```

- Adds permanent hosts from `cdspill_permanent_staff.json`
- Auto-detects guests from episode titles ("med [name]")
- Enriches with images/URLs from `cdspill_known_guests.json`

### 2. New guest appears?
When a new episode has a guest not in `cdspill_known_guests.json`:

```bash
uv run python3 lookup_guest.py "Guest Name"
```

This will:
1. Search Podchaser for the guest
2. Show results with profile images
3. Let you select the correct match
4. Add to `cdspill_known_guests.json` automatically

**With alias:**
```bash
uv run python3 lookup_guest.py "Full Name" --alias "Short Name"
```

### 3. Re-run enricher
```bash
uv run enrich_cdspill.py
```

Now the guest will have profile image and Podchaser URL!

## Examples

### Adding a new guest
```bash
$ uv run python3 lookup_guest.py "Mats Lindh"

🔍 Searching Podchaser for: Mats Lindh
============================================================
Query cost: 7
Points remaining: 12621

✓ Found 1 result(s):

1. Mats Lindh
   Image: ✓
   URL: https://www.podchaser.com/creators/mats-lindh-...

Auto-selecting the only result...

✓ Added to cdspill_known_guests.json:
   Name: Mats Lindh
   Image: ✓
   Profile: https://www.podchaser.com/creators/mats-lindh-...

Next: Run 'uv run enrich_cdspill.py' to use the new guest data
```

### Adding with alias
```bash
$ uv run python3 lookup_guest.py "Jan Anders Ekroll" --alias "Anders Ekroll"

✓ Adding alias: 'Anders Ekroll' → 'Jan Anders Ekroll'
```

Now episode titles with "med Anders Ekroll" will match "Jan Anders Ekroll" and get his profile data.

## Podchaser API Usage

**lookup_guest.py cost**: ~7-10 points per lookup
**enrich_cdspill.py cost**: 0 points (no API calls)

Only use Podchaser when adding new guests. The enricher runs offline using the JSON files.

## Manual Editing

You can also manually edit `cdspill_known_guests.json`:

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

## Current Status

**Permanent hosts**: 2 (Sigve, Mamen)
**Known guests**: 9 with profile images
**Aliases**: 3 name normalizations

Run `uv run enrich_cdspill.py` to see current counts.
