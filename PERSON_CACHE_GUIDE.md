# Person Data System for cd SPILL Feed Enricher

## Overview

The cd SPILL feed enricher uses a **config + cache hybrid system** for person data:

- **Permanent staff** (hosts, cover art designers, etc.): Defined in `cdspill_permanent_staff.json`
- **Guest data** (images, Podchaser URLs): Fetched from Podchaser API and cached in `cdspill_persons_cache.json`

This approach gives you control over permanent roles while automatically enriching with Podchaser metadata.

## How It Works

### 1. Cache Generation (`build_person_cache.py`)

This script fetches episode-level credits from Podchaser API and builds a local cache:

```bash
uv run python3 build_person_cache.py
```

**What it does:**
- Fetches all episodes and their credits from Podchaser
- Analyzes appearance patterns to distinguish:
  - **Permanent hosts**: Appear as host/announcer in >50% of episodes
  - **Production staff**: Appear in production roles (editor, producer, etc.) in >50% of episodes
  - **Guests**: Everyone else
- Saves results to `cdspill_persons_cache.json`

**API Cost:**
- First run: ~6,400 points (fetches ~130 episodes with credits)
- Subsequent runs: Same cost (re-fetches everything)
- **Important**: Only run this when you need to refresh the data!

### 2. Cache Structure (`cdspill_persons_cache.json`)

```json
{
  "podcast_id": "1540724",
  "podcast_title": "cd SPILL",
  "total_episodes": 79,
  "generated_at": "2025-12-01T15:00:00",
  "permanent_hosts": {
    "Sigve Baar Digernes": {
      "name": "Sigve Baar Digernes",
      "role": "host",
      "img": "https://creator-images.podchaser.com/71bbd16436f94f6bc85f2bb97e13298c.jpeg",
      "appearances": 98,
      "roles": {"host": 57, "announcer": 41}
    }
  },
  "production_staff": {
    "Erik André Vik Mamen": {
      "name": "Erik André Vik Mamen",
      "role": "socialMediaManager",
      "img": "https://...",
      "appearances": 332,
      "roles": {...}
    }
  },
  "guests": {
    "Roar Granevang": {
      "name": "Roar Granevang",
      "role": "guest",
      "img": "https://creator-images.podchaser.com/f612968bfc92c75a5cf078e5c1f623c1.jpeg",
      "appearances": 5,
      "roles": {"guest": 5}
    }
  }
}
```

### 3. Feed Enrichment (`enrich_cdspill.py`)

The enricher now loads person data from cache instead of API:

```bash
# Use cached data (recommended - no API calls)
uv run enrich_cdspill.py

# Rebuild cache from API, then enrich
uv run enrich_cdspill.py --podchaser
```

**What happens:**
- Loads `cdspill_persons_cache.json`
- Adds **permanent hosts** to channel level with images
- Adds **guests** to episodes (auto-detected from titles) with images from cache
- No API calls unless `--podchaser` flag is used

## Current Configuration

### Permanent Staff (`cdspill_permanent_staff.json`)

**Hosts** (added to feed at channel-level):
- **Sigve Baar Digernes** - ✓ img, ✓ href
- **Erik André Vik Mamen** - ✓ img, ✓ href

**Other permanent roles** (tracked but not currently added to feed):
- Halvor Blindheim (cover art designer)
- Anette Vik Jøsendal (cover art designer + occasional guest)
- Kristian Amlie (theme music)
- Joachim Froholt (consultant + occasional guest)

### Top Guests (Episode-level)
- Roar Granevang (5 appearances) - ✓ Has image
- Aleks Gisvold (6 appearances)
- Jostein Hakestad (6 appearances)
- Jan Anders Ekroll (6 appearances)
- And 32 more...

## When to Rebuild Cache

Rebuild the cache when:

1. **New episodes with new guests** have been published
2. **Podchaser data has been updated** (new profile images, corrected names, etc.)
3. **Role information has changed** (someone becomes a permanent host)

**Don't rebuild for every enrichment!** The cache is designed to be reused many times.

## API Points Management

### Current Status
- Points remaining: ~3,000 (as of last check)
- Cost per full cache rebuild: ~6,400 points

### Points Reset
Check Podchaser API documentation for point reset schedules.

### Monitor Usage
Test API cost before running:

```bash
uv run python3 -c "
import requests
from dotenv import load_dotenv
import os

load_dotenv()
# [authentication code...]

response = requests.post(
    'https://api.podchaser.com/graphql/cost',
    json={'query': '{ __typename }'},
    headers={'Authorization': f'Bearer {token}'}
)

print(f'Points remaining: {response.headers.get(\"X-Podchaser-Points-Remaining\")}')
"
```

## Manual Corrections

### Name Normalizations

The enricher supports aliases for name variations in episode titles:

```python
known_guests.update({
    "Aksel Bjerke": {"alias": "Aksel M. Bjerke"},  # Normalizes short name
    "Aleksander": {"alias": "Aleksander Hakestad"}  # Expands first name only
})
```

Add these in `enrich_cdspill.py` if episode titles use shortened names.

### Missing Images

If a person is missing an image in Podchaser:
1. Check if their profile exists on Podchaser
2. If yes, rebuild cache: `uv run python3 build_person_cache.py`
3. If no, consider manually adding image URL to cache file

## Troubleshooting

### "Cache file not found"
Run: `uv run python3 build_person_cache.py`

### "No hosts found"
Check `cdspill_persons_cache.json` for `permanent_hosts` field. Should contain at least Sigve Baar Digernes.

### Guests not getting images
1. Check if guest has image in cache: `grep "guestname" cdspill_persons_cache.json`
2. If not, rebuild cache (they may have added an image to Podchaser)

### API points depleted
Wait for points to reset, or use existing cache (it's designed for this!)

## Files

- `build_person_cache.py` - Cache generation script
- `cdspill_persons_cache.json` - Person data cache
- `enrich_cdspill.py` - Feed enricher (uses cache)
- `src/enrichment/podchaser_api.py` - Legacy API client (still used by cache builder)

## Future Improvements

- [ ] Incremental cache updates (only fetch new episodes)
- [ ] Cache expiration/staleness detection
- [ ] Support for episode-specific credits beyond auto-detection
- [ ] Merge production staff roles into feed (audio editor, cover art designer, etc.)
