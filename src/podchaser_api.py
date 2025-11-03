"""
Podchaser API Integration
Fetches person/creator information from Podchaser.
"""

import requests
from typing import List, Dict, Optional


class PodchaserAPI:
    """Client for interacting with Podchaser API."""

    BASE_URL = "https://api.podchaser.com/graphql"

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Podchaser API client.

        Args:
            api_key: Podchaser API key (required for authenticated requests)
        """
        self.api_key = api_key
        self.headers = {
            "Content-Type": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

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

            podcasts = data.get("data", {}).get("podcasts", {}).get("data", [])
            return podcasts[0] if podcasts else None

        except requests.RequestException as e:
            print(f"Error searching Podchaser: {e}")
            return None

    def get_podcast_creators(self, podcast_id: str) -> List[Dict[str, str]]:
        """
        Get creators/hosts for a podcast.

        Args:
            podcast_id: Podchaser podcast ID

        Returns:
            List of creator information dicts
        """
        query = """
        query GetPodcastCreators($podcastId: ID!) {
          podcast(identifier: {id: $podcastId}) {
            id
            title
            credits {
              person {
                id
                name
                imageUrl
                url
              }
              role {
                id
                name
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

            credits = data.get("data", {}).get("podcast", {}).get("credits", [])

            # Convert to podcast:person format
            persons = []
            for credit in credits:
                person = credit.get("person", {})
                role = credit.get("role", {})

                persons.append({
                    "name": person.get("name", ""),
                    "role": role.get("name", "host").lower(),
                    "href": person.get("url", ""),
                    "img": person.get("imageUrl", "")
                })

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
        podcast = self.search_podcast(podcast_name)
        if not podcast:
            print(f"Podcast '{podcast_name}' not found on Podchaser")
            return []

        podcast_id = podcast["id"]
        return self.get_podcast_creators(podcast_id)
