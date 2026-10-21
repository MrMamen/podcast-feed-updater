"""Hosts and guests: podcast:person at channel and episode level."""

from typing import Dict, List, Optional, Self

from lxml import etree

from src.common.base_feed import BaseFeed
from src.common.namespaces import PODCAST
from src.common.podcast_utils import TitleRules


class PersonsMixin(BaseFeed):
    """FeedEnricher methods for hosts and guests: podcast:person at channel and episode level."""

    def add_channel_persons(
        self,
        persons: List[Dict[str, str]]
    ) -> Self:
        """
        Add default hosts to channel level.

        Args:
            persons: List of person dicts with keys: name, role, img, href

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        # Ensure podcast namespace is registered
        self._ensure_podcast_namespace()

        # Insert after the (first block of) itunes tags for organization,
        # keeping the order of the list
        def is_itunes(elem):
            return isinstance(elem.tag, str) and 'itunes' in elem.tag

        children = list(self.channel)
        position = next(
            (i + 1 for i in range(len(children) - 1)
             if is_itunes(children[i]) and not is_itunes(children[i + 1])),
            len(children),
        )

        for offset, person_data in enumerate(persons):
            person_elem = etree.Element(
                f'{PODCAST}person',
                role=person_data.get('role', 'host')
            )
            person_elem.text = person_data['name']

            if 'img' in person_data:
                person_elem.set('img', person_data['img'])
            if 'href' in person_data:
                person_elem.set('href', person_data['href'])

            self.channel.insert(position + offset, person_elem)

        if persons:
            print(f"✓ Added {len(persons)} default host(s) to channel")
        return self

    def auto_detect_guests_from_titles(
        self,
        title_rules: Optional[TitleRules] = None,
        known_guests: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> Self:
        """
        Automatically detect and add guests from episode titles.

        Args:
            title_rules: How guests are named in titles ("Game med Guest A og Guest B").
                         None: only extra_episodes are added.
            known_guests: Optional dict mapping guest names to additional info
                         Example: {"Roar Granevang": {"href": "https://...", "img": "..."}}
                         Can include 'alias' key to normalize name variations:
                         {"Aksel Bjerke": {"alias": "Aksel M. Bjerke"}}
                         Can include 'extra_episodes' list to add guest to specific episodes by GUID:
                         {"Terje Høiback": {"href": "...", "extra_episodes": [{"guid": "...", "note": "..."}]}}

        Returns:
            Self for chaining
        """
        if self.channel is None:
            raise ValueError("Must fetch feed first")

        if known_guests is None:
            known_guests = {}
        if title_rules is None:
            title_rules = TitleRules()

        items = self.channel.findall('item')
        guest_count = 0
        extra_episodes_count = 0
        normalizations = []  # Track normalizations for reporting
        missing_metadata = []  # Track guests without profile images

        # First pass: Handle extra_episodes (manual additions by GUID)
        for guest_name, guest_info in known_guests.items():
            if 'extra_episodes' not in guest_info:
                continue

            # Skip if this is an alias entry
            if 'alias' in guest_info:
                continue

            for episode_spec in guest_info['extra_episodes']:
                episode_guid = episode_spec['guid']

                # Find item with matching GUID
                for item in items:
                    guid_elem = item.find('guid')
                    if guid_elem is None or not guid_elem.text:
                        continue

                    if guid_elem.text == episode_guid:
                        # Add guest to this episode (one person element per role)
                        roles = episode_spec.get('role', 'guest')
                        if isinstance(roles, str):
                            roles = [roles]

                        for role in roles:
                            person_elem = etree.Element(
                                f'{PODCAST}person',
                                role=role
                            )
                            person_elem.text = guest_name

                            if 'href' in guest_info:
                                person_elem.set('href', guest_info['href'])
                            if 'img' in guest_info:
                                person_elem.set('img', guest_info['img'])

                            item.append(person_elem)

                        extra_episodes_count += 1
                        break

        # Second pass: Auto-detect from titles
        for item in items:
            title_elem = item.find('title')
            if title_elem is None or not title_elem.text:
                continue

            title = title_elem.text

            # Create person element for each guest named in the title
            for guest_name in title_rules.extract_guests(title):
                # Check for alias/normalization
                original_name = guest_name
                if guest_name in known_guests and 'alias' in known_guests[guest_name]:
                    normalized_name = known_guests[guest_name]['alias']
                    normalizations.append(f"  '{original_name}' → '{normalized_name}'")
                    guest_name = normalized_name

                person_elem = etree.Element(
                    f'{PODCAST}person',
                    role='guest'
                )
                person_elem.text = guest_name

                # Look up canonical name first (guest_name is already normalized
                # from any alias). Falling back to original_name would return
                # an alias stub ({"alias": ...}) and miss the real href/img.
                guest_info = known_guests.get(guest_name, {})
                if not guest_info:
                    guest_info = known_guests.get(original_name, {})

                has_href = False
                if guest_info:
                    if 'href' in guest_info:
                        person_elem.set('href', guest_info['href'])
                        has_href = True
                    if 'img' in guest_info:
                        person_elem.set('img', guest_info['img'])

                # Track guests without href (Podchaser URL)
                # img is nice to have but not critical
                if not has_href:
                    missing_metadata.append({
                        'name': guest_name,
                        'original_name': original_name if original_name != guest_name else None,
                        'episode': title
                    })

                item.append(person_elem)
                guest_count += 1

        # Report summary
        total_added = guest_count + extra_episodes_count
        if extra_episodes_count > 0:
            print(f"✓ Added {total_added} guest appearances ({guest_count} auto-detected from titles, {extra_episodes_count} from extra_episodes)")
        else:
            print(f"✓ Auto-detected and added {guest_count} guests from episode titles")

        # Report normalizations if any
        if normalizations:
            print("\n  Name normalizations applied:")
            for norm in sorted(set(normalizations)):
                print(norm)

        # Report guests without metadata
        if missing_metadata:
            # Group by guest name to avoid duplicates
            unique_missing = {}
            for guest in missing_metadata:
                name = guest['name']
                if name not in unique_missing:
                    unique_missing[name] = {
                        'original_name': guest['original_name'],
                        'episodes': []
                    }
                unique_missing[name]['episodes'].append(guest['episode'])

            print(f"\n⚠ Found {len(unique_missing)} guest(s) without Podchaser URL (href):")
            for name, info in sorted(unique_missing.items()):
                episode_count = len(info['episodes'])
                if episode_count == 1:
                    print(f"  - {name} (1 episode)")
                else:
                    print(f"  - {name} ({episode_count} episodes)")

                # Show original name if it was normalized from an alias
                if info['original_name']:
                    print(f"    (detected as '{info['original_name']}' in titles)")

            print("\n💡 Add Podchaser profile with:")
            print("   uv run guests.py add \"Guest Name\"   (or: uv run guests.py refresh)")

            # If there are guests that might need aliases
            detected_names = [info['original_name'] for info in unique_missing.values()
                            if info['original_name']]
            if detected_names:
                print("\n💡 If name variations exist, add aliases with:")
                print("   uv run guests.py add \"Full Name\" --alias \"Short Name\"")

        return self
