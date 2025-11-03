#!/usr/bin/env python3
"""
Command-line interface for podcast feed processor.
"""

import argparse
import sys
from pathlib import Path
from feed_processor import PodcastFeedProcessor, create_filtered_feed
from feed_processor_xml import XMLPodcastFeedProcessor, create_filtered_feed_xml
from podchaser_api import PodchaserAPI


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Filter and enrich podcast RSS feeds",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Simple filter by title pattern
  python cli.py --source https://example.com/feed.xml --output filtered.xml --pattern "Tech Talk"

  # Filter and rename feed
  python cli.py --source https://example.com/feed.xml --output filtered.xml \\
                --pattern "My Show" --title "My Show - Filtered"

  # Use config file (advanced)
  python cli.py --config config.yaml
        """
    )

    # Input/output options
    parser.add_argument(
        "--source", "-s",
        help="Source podcast feed URL"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path for generated feed"
    )

    # Filter options
    parser.add_argument(
        "--pattern", "-p",
        help="Regex pattern to filter episode titles"
    )
    parser.add_argument(
        "--exclude",
        action="store_true",
        help="Exclude matching episodes instead of including them"
    )

    # Metadata options
    parser.add_argument(
        "--title", "-t",
        help="Override feed title"
    )
    parser.add_argument(
        "--description", "-d",
        help="Override feed description"
    )
    parser.add_argument(
        "--link", "-l",
        help="Override feed link"
    )

    # Config file option
    parser.add_argument(
        "--config", "-c",
        help="Path to YAML config file (see example_config.yaml)"
    )

    # Processing mode
    parser.add_argument(
        "--preserve-xml",
        action="store_true",
        default=True,
        help="Preserve original XML structure (default: True)"
    )
    parser.add_argument(
        "--use-feedgen",
        action="store_true",
        help="Use feedgen library (may not preserve all fields)"
    )

    args = parser.parse_args()

    # Config file mode
    if args.config:
        process_config_file(args.config)
        return

    # Simple mode requires source and output
    if not args.source or not args.output:
        parser.error("--source and --output are required (or use --config)")

    try:
        # Choose processor based on mode
        if args.use_feedgen:
            # Use feedgen-based processor (may not preserve all fields)
            processor = PodcastFeedProcessor(args.source)
            processor.fetch_feed()

            # Apply filter
            if args.pattern:
                processor.filter_by_title_pattern(
                    args.pattern,
                    keep_matching=not args.exclude
                )
            else:
                processor.filtered_entries = processor.parsed_feed.entries

            # Generate output
            processor.generate_feed(
                args.output,
                feed_title=args.title,
                feed_description=args.description,
                feed_link=args.link
            )

            print(f"Success! Generated {len(processor.filtered_entries)} episodes")
        else:
            # Use XML-based processor (preserves structure)
            processor = XMLPodcastFeedProcessor(args.source)
            processor.fetch_feed()

            # Apply filter
            if args.pattern:
                processor.filter_by_title_pattern(
                    args.pattern,
                    keep_matching=not args.exclude
                )
            else:
                processor.filtered_items = processor.items

            # Generate output
            processor.generate_feed(
                args.output,
                feed_title=args.title,
                feed_description=args.description,
                feed_link=args.link
            )

            print(f"Success! Generated {len(processor.filtered_items)} episodes")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def process_config_file(config_path: str):
    """Process feeds from a YAML config file."""
    import yaml

    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"Error reading config file: {e}", file=sys.stderr)
        sys.exit(1)

    feeds = config.get('feeds', [])
    if not feeds:
        print("No feeds defined in config file", file=sys.stderr)
        sys.exit(1)

    # Get Podchaser API key if configured
    podchaser_config = config.get('podchaser', {})
    api_key = podchaser_config.get('api_key') or None

    # Process each feed
    for feed_config in feeds:
        print(f"\n{'='*60}")
        print(f"Processing: {feed_config['name']}")
        print(f"{'='*60}")

        try:
            processor = PodcastFeedProcessor(feed_config['source_url'])
            processor.fetch_feed()

            # Apply filter
            filter_config = feed_config.get('filter', {})
            if filter_config:
                filter_type = filter_config.get('type')
                if filter_type == 'title_pattern':
                    pattern = filter_config['pattern']
                    keep = filter_config.get('keep_matching', True)
                    processor.filter_by_title_pattern(pattern, keep_matching=keep)
            else:
                processor.filtered_entries = processor.parsed_feed.entries

            # Apply enrichment
            enrich_config = feed_config.get('enrich', {})
            if enrich_config:
                persons_config = enrich_config.get('persons', {})

                # Static persons
                static_persons = persons_config.get('static', [])
                if static_persons:
                    # Apply to all episodes
                    for entry in processor.filtered_entries:
                        entry['podcast_persons'] = static_persons

                # Podchaser integration
                podchaser_config = persons_config.get('podchaser', {})
                if podchaser_config.get('enabled') and api_key:
                    podcast_name = podchaser_config['podcast_name']
                    api = PodchaserAPI(api_key)
                    creators = api.enrich_feed_with_creators(podcast_name)
                    if creators:
                        for entry in processor.filtered_entries:
                            entry['podcast_persons'] = creators

            # Ensure output directory exists
            output_path = Path(feed_config['output_file'])
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Generate feed
            metadata = feed_config.get('metadata', {})
            processor.generate_feed(
                feed_config['output_file'],
                feed_title=metadata.get('title'),
                feed_description=metadata.get('description'),
                feed_link=metadata.get('link')
            )

            print(f"✓ Success: {feed_config['output_file']}")

        except Exception as e:
            print(f"✗ Error processing {feed_config['name']}: {e}", file=sys.stderr)
            continue


if __name__ == "__main__":
    main()
