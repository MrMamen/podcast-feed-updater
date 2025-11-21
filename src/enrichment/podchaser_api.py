"""
Podchaser API Integration
Fetches person/creator information from Podchaser.
"""

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
