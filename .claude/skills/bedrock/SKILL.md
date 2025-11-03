---
name: using-aws-bedrock-api
description: Connect to AWS Bedrock API to interact with Claude models. Supports both text and structured JSON responses.
---

# Using AWS Bedrock API

## Instructions

The user uses AWS Bedrock for AI processing. The skill tells you how to use the Bedrock API in a way that is compatible with the users cloud enviroment.

## Environment

You can assume the following AWS credentials exist:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_SESSION_TOKEN` (optional, for temporary credentials)

When using Bedrock always use region "eu-central-1". The user can assist you in looking up valid models with

`aws bedrock list-inference-profiles --region eu-central-1|jq .inferenceProfileSummaries[].inferenceProfileId`

Don't ask for an update list unless the list below is insufficient:

- "eu.anthropic.claude-3-sonnet-20240229-v1:0"
- "eu.anthropic.claude-3-5-sonnet-20240620-v1:0"
- "eu.anthropic.claude-3-haiku-20240307-v1:0"
- "eu.meta.llama3-2-3b-instruct-v1:0"
- "eu.meta.llama3-2-1b-instruct-v1:0"
- "eu.amazon.nova-micro-v1:0"
- "eu.amazon.nova-lite-v1:0"
- "eu.mistral.pixtral-large-2502-v1:0"
- "eu.anthropic.claude-sonnet-4-20250514-v1:0"
- "eu.amazon.nova-pro-v1:0"
- "eu.anthropic.claude-3-7-sonnet-20250219-v1:0"
- "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
- "eu.cohere.embed-v4:0"
- "global.cohere.embed-v4:0"
- "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
- "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
- "global.anthropic.claude-haiku-4-5-20251001-v1:0"

## Usage

The template provided is a basic example on how to use Bedrock in Python. It can be used both standalone and as a library. Standalone usage:

**Basic prompt:**
```bash
uv run bedrock.py -p "Explain quantum computing"
```

**With system prompt:**
```bash
uv run bedrock.py -p "Write a story" -s "You are a creative writer"
```

**From files:**
```bash
uv run bedrock.py -f prompt.txt --system-file system.txt
```

**Structured JSON response:**
```bash
uv run bedrock.py -p "Analyze: 'Great product!'" --structured \
  --tool-description "Extract sentiment" --schema-file schema.json
```

**As a library:**
```python
from bedrock import send_to_claude
response = send_to_claude("Hello, Claude!")
```

## Template

See `templates/bedrock.py` for the complete implementation