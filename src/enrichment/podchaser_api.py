"""
Podchaser API Integration
Fetches person/creator information from Podchaser.
"""

import os
import sys

import requests
from typing import List, Dict, Optional


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

    def search_podcast(self, podcast_name: str) -> Optional[Dict]:
        """
        Search for a podcast by name.

        Args:
            podcast_name: Name of the podcast to search for

        Returns:
            Podcast information or None if not found
        """
        query = """
        query SearchPodcast($searchTerm: String!) {
          podcasts(searchTerm: $searchTerm, first: 1) {
            paginatorInfo {
              currentPage
              hasMorePages
            }
            data {
              id
              title
              description
              imageUrl
              webUrl
            }
          }
        }
        """

        variables = {"searchTerm": podcast_name}

        try:
            response = requests.post(
                self.BASE_URL,
                json={"query": query, "variables": variables},
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            # Debug: print response
            if "errors" in data:
                print(f"Podchaser API errors: {data['errors']}")
                return None

            podcasts = data.get("data", {}).get("podcasts", {}).get("data", [])

            if not podcasts:
                print(f"No podcasts found for search term: '{podcast_name}'")
                print(f"Try searching on https://www.podchaser.com/ first")

            return podcasts[0] if podcasts else None

        except requests.RequestException as e:
            print(f"Error searching Podchaser: {e}")
            if hasattr(e, 'response') and e.response:
                print(f"Response status: {e.response.status_code}")
                print(f"Response body: {e.response.text[:500]}")
            return None
        except Exception as e:
            print(f"Unexpected error: {e}")
            return None

    def get_podcast_creators(self, podcast_id: str) -> List[Dict[str, str]]:
        """
        Get creators/hosts for a podcast by analyzing episode credits.

        Since Podchaser doesn't reliably list permanent hosts at the podcast level,
        we fetch recent episodes and look for people with the "host" role.

        Args:
            podcast_id: Podchaser podcast ID

        Returns:
            List of creator information dicts
        """
        query = """
        query GetPodcastCreators($podcastId: String!) {
          podcast(identifier: {type: PODCHASER, id: $podcastId}) {
            id
            title
            episodes(first: 10) {
              data {
                id
                title
                credits {
                  data {
                    creator {
                      name
                      imageUrl
                    }
                    role {
                      code
                      title
                    }
                  }
                }
              }
            }
          }
        }
        """

        variables = {"podcastId": podcast_id}

        try:
            response = requests.post(
                self.BASE_URL,
                json={"query": query, "variables": variables},
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            # Debug
            if "errors" in data:
                print(f"Errors in credits query: {data['errors']}")
                return []

            episodes = data.get("data", {}).get("podcast", {}).get("episodes", {}).get("data", [])
            print(f"  Analyzing {len(episodes)} episodes to find hosts...")

            # Aggregate hosts across episodes
            host_counts = {}  # {name: {"count": N, "imageUrl": "...", "role_code": "..."}}

            for episode in episodes:
                credits = episode.get("credits", {}).get("data", [])
                for credit in credits:
                    creator = credit.get("creator", {})
                    role = credit.get("role", {})
                    role_code = role.get("code", "")

                    # Only count people with "host" role (not guestHost)
                    if role_code == "host":
                        name = creator.get("name", "")
                        if name:
                            if name not in host_counts:
                                host_counts[name] = {
                                    "count": 0,
                                    "imageUrl": creator.get("imageUrl", ""),
                                    "role_code": role_code
                                }
                            host_counts[name]["count"] += 1

            # Convert to podcast:person format
            persons = []
            for name, info in host_counts.items():
                print(f"    - {name}: appears as host in {info['count']} episode(s)")
                persons.append({
                    "name": name,
                    "role": "host",
                    "href": "",  # No direct URL in this API response
                    "img": info["imageUrl"] if info["imageUrl"] else ""
                })

            if not persons:
                print("  ⚠ No hosts found in episode credits")

            return persons

        except requests.RequestException as e:
            print(f"Error fetching creators from Podchaser: {e}")
            return []

    def enrich_feed_with_creators(self, podcast_name: str) -> List[Dict[str, str]]:
        """
        Convenience method to search for a podcast and get its creators.

        Args:
            podcast_name: Name of the podcast

        Returns:
            List of creator information
        """
        print(f"Searching for podcast: '{podcast_name}'")
        podcast = self.search_podcast(podcast_name)

        if not podcast:
            print(f"⚠ Podcast '{podcast_name}' not found on Podchaser")
            print(f"  Try different search terms or check https://www.podchaser.com/cdspill")
            return []

        print(f"✓ Found podcast: {podcast.get('title')} (ID: {podcast.get('id')})")
        podcast_id = podcast["id"]

        print(f"Fetching credits for podcast...")
        creators = self.get_podcast_creators(podcast_id)

        if not creators:
            print(f"⚠ No credits found for this podcast")

        return creators

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


def from_env(*, required: bool = True) -> Optional[PodchaserAPI]:
    """
    Build a ``PodchaserAPI`` client from ``PODCHASER_API_KEY`` /
    ``PODCHASER_API_SECRET`` environment variables.

    When ``required`` is True (default), exits the process with an error if
    credentials are missing. When False, returns ``None`` so callers can
    degrade gracefully (e.g. populate_guests.py adding guests without data).
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
