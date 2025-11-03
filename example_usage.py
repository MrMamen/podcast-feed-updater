#!/usr/bin/env python3
"""
Example usage of the podcast feed processor.
Run this to see the library in action.
"""

from src.feed_processor import PodcastFeedProcessor, create_filtered_feed
from src.podchaser_api import PodchaserAPI


def example_1_simple_filter():
    """Example 1: Simple filtering by title pattern."""
    print("\n" + "="*60)
    print("Example 1: Filter episodes by title pattern")
    print("="*60)

    # Use a real podcast feed (The Daily from NYT as example)
    source_url = "https://feeds.simplecast.com/54nAGcIl"  # The Daily

    processor = PodcastFeedProcessor(source_url)
    processor.fetch_feed()

    # Filter for episodes containing "Trump" in the title
    processor.filter_by_title_pattern("Trump|Election", keep_matching=True)

    # Generate filtered feed
    processor.generate_feed(
        "output/filtered_example.xml",
        feed_title="The Daily - Election Coverage Only",
        feed_description="Filtered episodes about elections"
    )


def example_2_split_feeds():
    """Example 2: Split a combined feed into separate feeds."""
    print("\n" + "="*60)
    print("Example 2: Split combined feed")
    print("="*60)

    # Example: Split a feed that contains multiple shows
    # You would replace this with your actual feed URL
    source_url = "https://example.com/combined-feed.xml"

    # First show
    processor1 = PodcastFeedProcessor(source_url)
    try:
        processor1.fetch_feed()
        processor1.filter_by_title_pattern("^Show A:", keep_matching=True)
        processor1.generate_feed(
            "output/show_a.xml",
            feed_title="Show A - Separated Feed"
        )
    except Exception as e:
        print(f"Note: This example requires a real combined feed. Error: {e}")

    # Second show
    processor2 = PodcastFeedProcessor(source_url)
    try:
        processor2.fetch_feed()
        processor2.filter_by_title_pattern("^Show B:", keep_matching=True)
        processor2.generate_feed(
            "output/show_b.xml",
            feed_title="Show B - Separated Feed"
        )
    except Exception as e:
        print(f"Note: This example requires a real combined feed. Error: {e}")


def example_3_custom_filter():
    """Example 3: Use a custom filter function."""
    print("\n" + "="*60)
    print("Example 3: Custom filter function")
    print("="*60)

    source_url = "https://feeds.simplecast.com/54nAGcIl"

    processor = PodcastFeedProcessor(source_url)
    processor.fetch_feed()

    # Custom filter: Only episodes longer than 20 minutes
    def long_episodes_only(entry):
        """Keep only episodes longer than 20 minutes."""
        # Get duration from iTunes tags if available
        itunes_duration = entry.get('itunes_duration', '0')
        try:
            # Duration can be in seconds or HH:MM:SS format
            if ':' in str(itunes_duration):
                parts = itunes_duration.split(':')
                seconds = sum(int(x) * 60**i for i, x in enumerate(reversed(parts)))
            else:
                seconds = int(itunes_duration)

            return seconds > 1200  # 20 minutes
        except:
            return True  # Include if we can't determine

    processor.filter_by_custom_function(long_episodes_only)

    processor.generate_feed(
        "output/long_episodes.xml",
        feed_title="The Daily - Long Episodes Only (>20min)"
    )


def example_4_enrich_with_persons():
    """Example 4: Enrich feed with podcast:person tags."""
    print("\n" + "="*60)
    print("Example 4: Enrich with person tags")
    print("="*60)

    source_url = "https://feeds.simplecast.com/54nAGcIl"

    processor = PodcastFeedProcessor(source_url)
    processor.fetch_feed()

    # Keep first 5 episodes for demo
    processor.filtered_entries = processor.parsed_feed.entries[:5]

    # Add static person information
    # In a real scenario, you'd map this to specific episodes
    static_persons = [
        {
            "name": "Michael Barbaro",
            "role": "host",
            "href": "https://www.nytimes.com/by/michael-barbaro"
        }
    ]

    # Add to all filtered episodes
    for entry in processor.filtered_entries:
        entry['podcast_persons'] = static_persons

    processor.generate_feed(
        "output/enriched_with_persons.xml",
        feed_title="The Daily - With Host Info"
    )

    print("\nNote: podcast:person tags are prepared but require extended feedgen support")


def example_5_podchaser_integration():
    """Example 5: Fetch creator info from Podchaser."""
    print("\n" + "="*60)
    print("Example 5: Podchaser API integration")
    print("="*60)

    # Note: This requires a Podchaser API key
    # Get one at: https://www.podchaser.com/api
    api_key = None  # Set your API key here

    if not api_key:
        print("Skipping: Requires PODCHASER_API_KEY")
        print("Get an API key at: https://www.podchaser.com/api")
        return

    api = PodchaserAPI(api_key)

    # Search for a podcast
    podcast = api.search_podcast("The Daily")
    if podcast:
        print(f"Found podcast: {podcast['title']}")
        print(f"  Description: {podcast['description'][:100]}...")

        # Get creators
        creators = api.get_podcast_creators(podcast['id'])
        print(f"\nCreators ({len(creators)}):")
        for creator in creators:
            print(f"  - {creator['name']} ({creator['role']})")
    else:
        print("Podcast not found")


def example_6_convenience_function():
    """Example 6: Use the convenience function."""
    print("\n" + "="*60)
    print("Example 6: Using convenience function")
    print("="*60)

    create_filtered_feed(
        source_url="https://feeds.simplecast.com/54nAGcIl",
        output_file="output/convenience_example.xml",
        title_pattern="Ukraine|Russia",
        new_title="The Daily - Ukraine Coverage"
    )


if __name__ == "__main__":
    import os

    # Create output directory
    os.makedirs("output", exist_ok=True)

    print("\n" + "="*60)
    print("PODCAST FEED PROCESSOR - EXAMPLES")
    print("="*60)

    try:
        # Run examples
        example_1_simple_filter()
        example_2_split_feeds()
        example_3_custom_filter()
        example_4_enrich_with_persons()
        example_5_podchaser_integration()
        example_6_convenience_function()

        print("\n" + "="*60)
        print("Examples completed! Check the 'output/' directory for results.")
        print("="*60 + "\n")

    except KeyboardInterrupt:
        print("\n\nExamples interrupted by user")
    except Exception as e:
        print(f"\n\nError running examples: {e}")
        import traceback
        traceback.print_exc()
