#!/usr/bin/env python3
"""
Log hook events to review the formatting of hook input data.
"""

import sys
import json
from datetime import datetime
from pathlib import Path

def log_hook_event(hook_type: str, stdin_data: str):
    """Log hook event data to a file."""
    log_dir = Path.home() / ".claude" / "hook-logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "hook-events.log"

    timestamp = datetime.now().isoformat()

    # Try to parse as JSON for pretty printing
    try:
        data = json.loads(stdin_data) if stdin_data.strip() else {}
        data_str = json.dumps(data, indent=2)
    except json.JSONDecodeError:
        data_str = stdin_data

    log_entry = f"""
{'='*80}
Timestamp: {timestamp}
Hook Type: {hook_type}
{'='*80}
{data_str}
{'='*80}

"""

    with open(log_file, 'a') as f:
        f.write(log_entry)

    print(f"✓ Logged {hook_type} event to {log_file}", file=sys.stderr)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: log-hook-event.py <hook_type>", file=sys.stderr)
        sys.exit(1)

    hook_type = sys.argv[1]
    stdin_data = sys.stdin.read()

    log_hook_event(hook_type, stdin_data)
