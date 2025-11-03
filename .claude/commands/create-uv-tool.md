# Create UV One-Shot Tool

Create a new one-shot Python tool using UV with PEP 723 script format for rapid prototyping and utility scripts.

## Instructions

You are tasked with creating a standalone Python tool that can be executed directly using UV. Follow this structure and checklist:

### 1. Tool Structure Requirements

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

Place the tool in a new folder.

### 2. Common Dependencies for Tools

Choose appropriate dependencies based on tool purpose:
- **CLI interfaces:** `click`, `typer`, `argparse`
- **HTTP requests:** `requests`, `httpx`
- **Rich output:** `rich`, `colorama`
- **File handling:** `pathlib` (built-in), `pydantic`
- **Data processing:** `pandas`, `polars`
- **Config/YAML:** `pyyaml`, `toml`
- **Cloud services:** `boto3` (AWS), `azure-storage-blob`

### 3. Tool Template Structure

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

After creating the tool:
```bash
# Make executable
chmod +x tool-name.py

# Run with UV
uv run tool-name.py --help

# Or run directly (if UV is in PATH)
./tool-name.py --help
```

### 6. Verification Checklist

Before completing, verify:
- [ ] PEP 723 script headers are correct
- [ ] All required dependencies are listed
- [ ] Tool has meaningful help text
- [ ] Error handling is implemented
- [ ] Output is user-friendly with Rich
- [ ] Tool serves a single, clear purpose
- [ ] CLI interface is intuitive
- [ ] File permissions allow execution

## Common Pitfalls to Avoid

❌ **Don't forget the shebang** - `#!/usr/bin/env python3` is required
❌ **Don't mix script types** - This is for standalone tools, not packages
❌ **Don't over-engineer** - Keep tools simple and focused
❌ **Don't skip error handling** - Tools should fail gracefully
❌ **Don't ignore user experience** - Use Rich for better output

## Success Criteria

✅ Tool runs independently with `uv run`
✅ Dependencies are correctly specified in script header
✅ CLI interface is clean and helpful
✅ Error messages are clear and actionable
✅ Output is well-formatted with Rich
✅ Tool serves its intended purpose effectively