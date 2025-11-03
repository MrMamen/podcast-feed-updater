# Claude Code Project Starter

A template and setup tool for quickly bootstrapping Claude Code projects with best practices and consistent configuration.

## Quick Start

### Installation

```bash
# Create alias (bash/zsh)
echo 'alias claude-setup="uv run ~/tools/claude-setup-tool/claude-setup.py"' >> ~/.bashrc
source ~/.bashrc
```

### Usage

```bash
# Setup new project
cd my-new-project
claude-setup

# Preview changes without copying
claude-setup --dry-run

# Update existing project
claude-setup --backup
```

## What's Included

- **Claude Configuration** - Pre-configured settings with AWS Bedrock support
- **Slash Commands** - `/explore`, `/create-uv-tool`, `/create-subagent`
- **Dev Container** - Ready-to-use development environment
- **Smart Conflict Resolution** - Interactive file handling with diff viewing
- **Git Integration** - Automatic repository initialization

## Features

- 🚀 One-command project setup
- 🔄 Keep configs synchronized across projects
- 👀 Preview mode with `--dry-run`
- 🛡️ Safe operations with backup support
- 🎨 Rich CLI interface

## Requirements

- [UV](https://docs.astral.sh/uv/) - Python package manager
- Python 3.12+ (managed by UV)
- Git (optional, for repo initialization)

## Documentation

See `claude-setup-tool/README.md` for detailed usage and options.
