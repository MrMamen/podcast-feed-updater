#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "rich",
# ]
# ///

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from pathlib import Path
import sys
import json

console = Console()

def load_memories():
    """
    Load and display all memories from the .memories/ folder.
    """
    memories_dir = Path.cwd() / '.memories'

    # Check if .memories directory exists
    if not memories_dir.exists():
        console.print("[dim]No .memories/ folder found. Memories will be saved here when .transcripts are analyzed.[/dim]")
        return

    # Get all memory files (both .json and legacy .txt)
    json_files = sorted(memories_dir.glob('*.json'))
    txt_files = sorted(memories_dir.glob('*.txt'))
    memory_files = json_files + txt_files

    if not memory_files:
        console.print("[dim]No memories found in .memories/ folder.[/dim]")
        return

    # Display header
    console.print()
    console.print(f"[bold cyan]📝 Session Memories ({len(memory_files)})[/bold cyan]")
    console.print()

    # Display each memory
    for memory_file in memory_files:
        try:
            if memory_file.suffix == '.json':
                # Parse JSON memory format
                memory_data = json.loads(memory_file.read_text())
                memory_text = memory_data.get('memory', '').strip()

                # Build subtitle with metadata
                dissatisfaction = memory_data.get('dissatisfaction_level', 'unknown')
                correction = memory_data.get('correction_detected', False)

                subtitle = None
                if dissatisfaction != 'unknown' and correction:
                    subtitle = f"[dim]dissatisfaction: {dissatisfaction} | correction detected[/dim]"

                if memory_text:
                    console.print(Panel(
                        memory_text,
                        title=f"[cyan]{memory_file.stem}[/cyan]",
                        subtitle=subtitle,
                        border_style="cyan",
                        padding=(0, 1)
                    ))
                    console.print()
            else:
                # Legacy text format
                content = memory_file.read_text().strip()
                if content:
                    console.print(Panel(
                        content,
                        title=f"[cyan]{memory_file.stem}[/cyan]",
                        border_style="cyan",
                        padding=(0, 1)
                    ))
                    console.print()
        except json.JSONDecodeError as e:
            console.print(f"[yellow]⚠ Could not parse {memory_file.name}: {e}[/yellow]")
        except Exception as e:
            console.print(f"[yellow]⚠ Could not read {memory_file.name}: {e}[/yellow]")

if __name__ == "__main__":
    try:
        load_memories()
    except Exception as e:
        console.print(f"[bold red]✗ Error: {e}[/bold red]")
        sys.exit(1)
