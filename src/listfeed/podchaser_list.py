"""
Fetch a Podchaser list and structure it into sections of episodes.

A Podchaser list (e.g. https://www.podchaser.com/lists/...) is exposed via the
GraphQL ``list`` query. The visual "sections" a curator sees on the website are
not a native field — they are ``ListHeading`` entries interleaved in the item
stream. We sort items by ``position`` and start a new section at each heading.

IMPORTANT: the list identifier the API wants is the *numeric* internal id, NOT
the hashid in the URL tail (passing the hashid silently resolves a different
list). Resolve the numeric id with :func:`resolve_list_id` when you only have a
search term / slug.
"""

import sys
from typing import Dict, List, Optional

import requests

from src.enrichment.podchaser_api import PodchaserAPI

# Episode fields needed to build a complete, playable RSS item. audioUrl is the
# real enclosure URL (kept verbatim, so any source-side op3 prefix is preserved).
_LIST_QUERY = """
query GetList($id: ID!, $first: Int!) {
  list(identifier: {type: PODCHASER, id: $id}) {
    id
    title
    description
    url
    updatedAt
    items(first: $first) {
      paginatorInfo { total hasMorePages }
      data {
        position
        item {
          __typename
          ... on ListHeading { heading }
          ... on Episode {
            id
            title
            htmlDescription
            audioUrl
            url
            webUrl
            imageUrl
            airDate
            guid
            length
            fileSize
            explicit
            episodeType
            podcast { title webUrl imageUrl }
          }
        }
      }
    }
  }
}
"""

_COUNT_QUERY = """
query CountList($id: ID!) {
  list(identifier: {type: PODCHASER, id: $id}) {
    items(first: 1) { paginatorInfo { total } }
  }
}
"""

_SEARCH_QUERY = """
query FindList($term: String!) {
  lists(searchTerm: $term, first: 10) {
    data { id title url }
  }
}
"""


def _post(api: PodchaserAPI, query: str, variables: Dict) -> Dict:
    """POST a query to the real endpoint, logging point cost, returning JSON data."""
    response = requests.post(
        api.BASE_URL,
        json={"query": query, "variables": variables},
        headers=api.headers,
        timeout=30,
    )
    cost = response.headers.get("X-Podchaser-Query-Cost")
    remaining = response.headers.get("X-Podchaser-Points-Remaining")
    print(f"  query cost: {cost} points  (remaining: {remaining})")

    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
    result = response.json()
    if "errors" in result:
        raise RuntimeError(f"GraphQL errors: {result['errors']}")
    return result.get("data", {})


def resolve_list_id(api: PodchaserAPI, search_term: str,
                    expected_title: Optional[str] = None) -> Optional[str]:
    """
    Find a list's numeric id from a search term (prefer an exact title match).

    Returns the numeric id string, or None if nothing matched.
    """
    print(f"Resolving list id for: {search_term!r}")
    data = _post(api, _SEARCH_QUERY, {"term": search_term})
    candidates = data.get("lists", {}).get("data", [])
    if not candidates:
        print("  ⚠ No lists matched")
        return None

    if expected_title:
        for c in candidates:
            if c.get("title", "").strip().lower() == expected_title.strip().lower():
                print(f"  ✓ Exact match: {c['title']!r} (id {c['id']})")
                return c["id"]

    best = candidates[0]
    print(f"  ✓ Best match: {best['title']!r} (id {best['id']})")
    return best["id"]


def get_list_size(api: PodchaserAPI, list_id: str) -> int:
    """Cheap query returning the total number of items in the list."""
    data = _post(api, _COUNT_QUERY, {"id": list_id})
    return data.get("list", {}).get("items", {}).get("paginatorInfo", {}).get("total", 0)


def fetch_list(api: PodchaserAPI, list_id: str, *, first: Optional[int] = None,
               min_remaining: int = 12000) -> Dict:
    """
    Fetch the list and return it structured into sections.

    Sets ``first`` to the actual list size (one cheap count query) so we never
    pay for empty item slots. Estimates the full query cost via the free
    ``/cost`` endpoint first and aborts if running it would drop the remaining
    point balance below ``min_remaining``.

    Returns::

        {
          "title", "description", "url", "updatedAt", "total",
          "sections": [{"heading": str | None, "episodes": [episode_dict, ...]}],
        }
    """
    if first is None:
        size = get_list_size(api, list_id)
        first = max(size, 1)
        print(f"List has {size} item(s); fetching first={first}")

    variables = {"id": list_id, "first": first}

    # Free pre-flight: validates the query AND tells us the cost before spending.
    est = api.estimate_cost(_LIST_QUERY, variables)
    if est.get("errors"):
        raise RuntimeError(f"Query invalid (no points spent): {est['errors']}")
    cost, remaining = est.get("cost"), est.get("remaining")
    print(f"Estimated cost: {cost} points  (remaining: {remaining})")
    if cost is not None and remaining is not None and (remaining - cost) < min_remaining:
        raise RuntimeError(
            f"Aborting: running this query (~{cost} pts) would leave "
            f"{remaining - cost} pts, below the {min_remaining} pt safety floor."
        )

    print("Fetching list contents...")
    data = _post(api, _LIST_QUERY, variables)
    lst = data.get("list")
    if not lst:
        raise RuntimeError(f"List id {list_id!r} did not resolve to a list.")

    items = lst.get("items", {})
    if items.get("paginatorInfo", {}).get("hasMorePages"):
        print("  ⚠ List has more pages than fetched — increase 'first'.")

    return _structure(lst)


def _structure(lst: Dict) -> Dict:
    """Group the flat item stream into sections, ordered by curator position."""
    rows = sorted(lst.get("items", {}).get("data", []),
                  key=lambda r: (r.get("position") or 0))

    sections: List[Dict] = []
    current = {"heading": None, "episodes": []}
    for row in rows:
        item = row.get("item") or {}
        typename = item.get("__typename")
        if typename == "ListHeading":
            # Start a new section. Only keep the implicit leading section if it
            # actually collected episodes.
            if current["episodes"] or current["heading"] is not None:
                sections.append(current)
            current = {"heading": item.get("heading"), "episodes": []}
        elif typename == "Episode":
            current["episodes"].append({**item, "position": row.get("position")})
        # Podcast items (if any) are ignored — this builder is episode-only.
    if current["episodes"] or current["heading"] is not None:
        sections.append(current)

    return {
        "title": lst.get("title"),
        "description": lst.get("description"),
        "url": lst.get("url"),
        "updatedAt": lst.get("updatedAt"),
        "total": lst.get("items", {}).get("paginatorInfo", {}).get("total"),
        "sections": sections,
    }
