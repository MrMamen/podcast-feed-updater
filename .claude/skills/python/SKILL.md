---
name: python-scripting
description: How to use UV package manager and what libraries that are recommended for Python development
---

# Python scripting

## Instructions

When asked to use the develop in Python always use the UV package manager. This makes the code you write more portable. UV package manager can be used in a number of ways but the best way is to include a PEP 723 header in your scripts to make them self contained.

### 1. Structure Requirements

**CRITICAL:** Use the exact PEP 723 script format:
```python
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "click",
#     "requests", 
#     "rich",
#     # Add other dependencies as needed
# ]
# ///
```

Place the script in a new folder.

### 2. Common Dependencies 

Choose appropriate dependencies based on script purpose:
- **CLI interfaces:** `click`, `typer`, `argparse`
- **HTTP requests:** `requests`, `httpx`
- **Rich output:** `rich`, `colorama`
- **File handling:** `pathlib` (built-in), `pydantic`
- **Data processing:** `pandas`, `polars`
- **Config/YAML:** `pyyaml`, `toml`
- **Cloud services:** `boto3` (AWS), `azure-storage-blob`
- **Graphs:** `pyplot`

### 3. Template Structure

```python
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "click",
#     "rich",
#     # Add specific dependencies
# ]
# ///

import click
from rich.console import Console
import sys

console = Console()

@click.command()
@click.option('--input', '-i', help='Input parameter')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def main(input, verbose):
    """
    Brief description of what this tool does.
    
    Longer description with usage examples.
    """
    try:
        # Tool logic here
        console.print("[bold green]✓ Success[/bold green]")
        
    except Exception as e:
        console.print(f"[bold red]✗ Error: {e}[/bold red]")
        sys.exit(1)

if __name__ == "__main__":
    main()
```

### 5. After creation

After creating the script:
```bash
# Make executable
chmod +x script-name.py

# Run with UV
uv run script-name.py --help

# Or run directly (if UV is in PATH)
./script-name.py --help
```

### 6. Verification Checklist

Before completing, verify:
- [ ] PEP 723 script headers are correct
- [ ] All required dependencies are listed
- [ ] Script has meaningful help text
- [ ] Error handling is implemented
- [ ] Output is user-friendly with Rich
- [ ] CLI interface is intuitive
- [ ] File permissions allow execution

## Success Criteria

✅ Tool runs independently with `uv run`
✅ Dependencies are correctly specified in script header
✅ CLI interface is clean and helpful
✅ Error messages are clear and actionable
✅ Output is well-formatted with Rich