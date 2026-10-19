"""
Podchaser API Integration
Fetches person/creator information from Podchaser.
"""

import os
import sys
from typing import Dict, List, Optional

import requests


class PodchaserAPI:
    """Client for interacting with Podchaser API."""

    BASE_URL = "https://api.podchaser.com/graphql"

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        """
        Initialize Podchaser API client.

        Args:
            api_key: Podchaser API key (client_id)
            api_secret: Podchaser API secret (client_secret)
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = None
        self.headers = {
            "Content-Type": "application/json",
        }

        # If credentials provided, get access token
        if api_key and api_secret:
            self._get_access_token()

    def _get_access_token(self) -> None:
        """Get OAuth access token using client credentials."""
        mutation = """
        mutation {
            requestAccessToken(
                input: {
                    grant_type: CLIENT_CREDENTIALS
                    client_id: "%s"
                    client_secret: "%s"
                }
            ) {
                access_token
                token_type
                expires_in
            }
        }
        """ % (self.api_key, self.api_secret)

        try:
            response = requests.post(
                self.BASE_URL,
                json={"query": mutation},
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                print(f"Error getting access token: {data['errors']}")
                return

            token_data = data.get("data", {}).get("requestAccessToken", {})
            self.access_token = token_data.get("access_token")

            if self.access_token:
                self.headers["Authorization"] = f"Bearer {self.access_token}"
                print("✓ Successfully authenticated with Podchaser API")
            else:
                print("⚠ No access token received")

        except requests.RequestException as e:
            print(f"Error requesting access token: {e}")

    def search_creator(self, name: str, first: int = 5) -> List[Dict]:
        """
        Search for creators (people) on Podchaser by name.

        Returns a list of dicts with ``name``, ``imageUrl`` and ``url`` keys.
        """
        query = '''
        query {
          creators(searchTerm: "%s", first: %d) {
            data {
              name
              imageUrl
              url
            }
          }
        }
        ''' % (name, first)

        response = requests.post(
            self.BASE_URL,
            json={"query": query},
            headers=self.headers,
            timeout=15,
        )

        cost = response.headers.get("X-Podchaser-Query-Cost")
        remaining = response.headers.get("X-Podchaser-Points-Remaining")
        if cost is not None:
            print(f"Query cost: {cost}")
        if remaining is not None:
            print(f"Points remaining: {remaining}")

        result = response.json()
        if "errors" in result:
            print(f"❌ Error: {result['errors']}")
            return []

        return result.get("data", {}).get("creators", {}).get("data", [])

    def search_episode(self, podcast_id: str, episode_title: str, first: int = 5) -> Optional[Dict]:
        """
        Search for an episode within a specific podcast by title.

        Returns the best match (exact-match preferred, otherwise first result),
        or None.
        """
        query = '''
        query {
          podcast(identifier: { type: PODCHASER, id: "%s" }) {
            title
            episodes(searchTerm: "%s", first: %d) {
              data {
                id
                title
                url
              }
            }
          }
        }
        ''' % (podcast_id, episode_title, first)

        response = requests.post(
            self.BASE_URL,
            json={"query": query},
            headers=self.headers,
            timeout=15,
        )

        cost = response.headers.get("X-Podchaser-Query-Cost")
        remaining = response.headers.get("X-Podchaser-Points-Remaining")
        if cost is not None:
            print(f"Query cost: {cost}")
        if remaining is not None:
            print(f"Points remaining: {remaining}")

        result = response.json()
        if "errors" in result:
            print(f"❌ Error: {result['errors']}")
            return None

        episodes = (
            result.get("data", {}).get("podcast", {}).get("episodes", {}).get("data", [])
        )

        for episode in episodes:
            if episode.get("title", "").lower() == episode_title.lower():
                return episode

        return episodes[0] if episodes else None

    def fetch_episode_credits(self, episode_id: str) -> List[Dict]:
        """Return the credits list for a Podchaser episode id."""
        query = '''
        query {
          episode(identifier: { type: PODCHASER, id: "%s" }) {
            title
            credits(first: 100) {
              data {
                role {
                  title
                }
                creator {
                  name
                  imageUrl
                  url
                }
              }
            }
          }
        }
        ''' % episode_id

        response = requests.post(
            self.BASE_URL,
            json={"query": query},
            headers=self.headers,
            timeout=15,
        )

        cost = response.headers.get("X-Podchaser-Query-Cost")
        remaining = response.headers.get("X-Podchaser-Points-Remaining")
        if cost is not None:
            print(f"Query cost: {cost}")
        if remaining is not None:
            print(f"Points remaining: {remaining}")

        if response.status_code != 200:
            print(f"❌ HTTP Error {response.status_code}: {response.text}")
            return []

        result = response.json()
        if "errors" in result:
            print(f"❌ GraphQL Error: {result['errors']}")
            return []

        episode = result.get("data", {}).get("episode")
        if not episode:
            return []

        return episode.get("credits", {}).get("data", [])

    def estimate_cost(self, query: str, variables: Optional[Dict] = None) -> Dict:
        """
        Estimate the query point cost WITHOUT spending points.

        POSTs the same payload to the dedicated ``/graphql/cost`` endpoint.
        GraphQL validation still runs there, so a malformed query (e.g. a field
        that doesn't exist in the schema) shows up in ``errors`` before any
        points are ever spent on the real ``/graphql`` endpoint.

        Returns a dict: ``{"cost", "remaining", "errors"}`` where cost/remaining
        are ints (or None if the headers are absent) and errors is the GraphQL
        errors list (or None).
        """
        try:
            response = requests.post(
                self.BASE_URL + "/cost",
                json={"query": query, "variables": variables or {}},
                headers=self.headers,
                timeout=15,
            )
        except requests.RequestException as e:
            return {"cost": None, "remaining": None, "errors": [str(e)]}

        cost = response.headers.get("X-Podchaser-Query-Cost")
        remaining = response.headers.get("X-Podchaser-Points-Remaining")
        try:
            errors = response.json().get("errors")
        except ValueError:
            errors = None

        return {
            "cost": int(cost) if cost is not None else None,
            "remaining": int(remaining) if remaining is not None else None,
            "errors": errors,
        }


def from_env(*, required: bool = True) -> Optional[PodchaserAPI]:
    """
    Build a ``PodchaserAPI`` client from ``PODCHASER_API_KEY`` /
    ``PODCHASER_API_SECRET`` environment variables.

    When ``required`` is True (default), exits the process with an error if
    credentials are missing. When False, returns ``None`` so callers can
    degrade gracefully (e.g. guests.py sync adding guests without data).
    """
    api_key = os.getenv("PODCHASER_API_KEY")
    api_secret = os.getenv("PODCHASER_API_SECRET")

    if not api_key or not api_secret:
        message = (
            "❌ Missing Podchaser credentials in .env file\n"
            "   PODCHASER_API_KEY and PODCHASER_API_SECRET required"
        )
        if required:
            print(message)
            sys.exit(1)
        print("⚠ Missing Podchaser credentials in .env file")
        return None

    client = PodchaserAPI(api_key=api_key, api_secret=api_secret)
    if not client.access_token:
        if required:
            print("❌ Failed to authenticate with Podchaser")
            sys.exit(1)
        return None
    return client
