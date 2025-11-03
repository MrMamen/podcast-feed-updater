#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "click",
#     "rich",
#     "boto3",
# ]
# ///

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
import boto3
import json
import sys
from pathlib import Path
from datetime import datetime

console = Console()

def call_bedrock(transcript_content: str) -> dict:
    """
    Call AWS Bedrock to analyze the transcript and suggest improvements.
    Returns a structured response with a single memory suggestion if found.
    """
    bedrock = boto3.client('bedrock-runtime', region_name='eu-central-1')

    system_prompt = """Analyze this transcript to find genuine agent behavior corrections.

ONLY create memories when:
1. User was dissatisfied with how agent operated (not just the task result)
2. User explicitly redirected, corrected, or instructed different behavior
3. The correction reveals a repeatable preference

HIGH-VALUE INDICATORS (look for these):
- User said "no, actually..." or "instead..."
- User asked agent to change approach mid-session
- User expressed frustration with agent's process
- User provided explicit instructions about future behavior
- User corrected same behavior multiple times

LOW-VALUE INDICATORS (ignore these):
- Routine task requests and completions
- User satisfied with agent's work
- No behavioral corrections or preferences stated
- Just information gathering or questions
- User providing task-specific details

SCORING RUBRIC:
- Is there explicit user correction? (Required: Yes)
- Is dissatisfaction clear? (Required: Yes)
- Will this repeat in 5+ sessions? (Required: Likely)
- Is it about agent behavior vs task content? (Required: Behavior)

Response:
{
  "has_suggestion": true/false,
  "correction_detected": true/false,
  "dissatisfaction_level": "none/low/medium/high",
  "memory": "What to change (if applicable)",
  "reasoning": "What correction occurred and why it matters"
}"""

    user_prompt = f"""Analyze this session transcript and identify ONE specific improvement for the agent:

<transcript>
{transcript_content}
</transcript>

Provide your response in the JSON format specified."""

    response = bedrock.invoke_model(
        modelId='eu.anthropic.claude-sonnet-4-5-20250929-v1:0',
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "temperature": 0.2,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": user_prompt
                }
            ]
        })
    )

    response_body = json.loads(response['body'].read())

    # Extract text from response
    text_content = response_body['content'][0]['text']

    # Parse JSON from the response
    # Handle potential markdown code blocks
    if '```json' in text_content:
        text_content = text_content.split('```json')[1].split('```')[0].strip()
    elif '```' in text_content:
        text_content = text_content.split('```')[1].split('```')[0].strip()

    return json.loads(text_content)

@click.command()
@click.argument('transcript_path', type=click.Path(exists=True, path_type=Path))
@click.option('--output', '-o', type=click.Path(path_type=Path), help='Output file for the memory (overrides default .memories/ location)')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def main(transcript_path: Path, output: Path, verbose: bool):
    """
    Review a session transcript and generate actionable memory suggestions.

    This tool uses AWS Bedrock (Claude) to analyze transcripts found under
    .transcripts/ and identify specific improvements the agent should make
    in future sessions.

    By default, memories are saved to .memories/ folder with a filename based on the transcript.

    Example:
        uv run review-transcript.py .transcripts/session-001.txt
        uv run review-transcript.py .transcripts/session-001.txt -o custom-memory.txt
    """
    try:
        # Read transcript
        console.print(f"[cyan]Reading transcript:[/cyan] {transcript_path}")
        transcript_content = transcript_path.read_text()

        if verbose:
            console.print(f"[dim]Transcript length: {len(transcript_content)} characters[/dim]")

        # Analyze with Bedrock
        console.print("[cyan]Analyzing transcript with Bedrock...[/cyan]")
        result = call_bedrock(transcript_content)

        # Display results
        if result['has_suggestion']:
            console.print()
            console.print(Panel(
                result['memory'],
                title="[bold green]✓ Memory Suggestion[/bold green]",
                border_style="green"
            ))
            console.print()

            if verbose:
                # Display additional diagnostic info
                correction = result.get('correction_detected', 'unknown')
                dissatisfaction = result.get('dissatisfaction_level', 'unknown')
                console.print(f"[cyan]Correction Detected:[/cyan] {correction}")
                console.print(f"[cyan]Dissatisfaction Level:[/cyan] {dissatisfaction}")
                console.print()
                console.print("[cyan]Reasoning:[/cyan]")
                console.print(Markdown(result['reasoning']))
                console.print()

            # Determine output location
            if output:
                output_path = output
            else:
                # Default to .memories folder
                memories_dir = Path.cwd() / '.memories'
                memories_dir.mkdir(exist_ok=True)

                # Generate filename from transcript name (use .json extension)
                memory_filename = transcript_path.stem.replace('session_', 'memory_') + '.json'
                output_path = memories_dir / memory_filename

            # Prepare memory metadata
            memory_data = {
                "memory": result['memory'],
                "correction_detected": result.get('correction_detected', False),
                "dissatisfaction_level": result.get('dissatisfaction_level', 'unknown'),
                "reasoning": result.get('reasoning', ''),
                "created_at": datetime.now().isoformat(),
                "transcript_path": str(transcript_path),
                "transcript_name": transcript_path.name
            }

            # Save to file as JSON
            output_path.write_text(json.dumps(memory_data, indent=2))
            console.print(f"[green]✓ Memory saved to:[/green] {output_path}")
        else:
            console.print()
            console.print(Panel(
                "No actionable memory suggestion found in this transcript.",
                title="[bold yellow]⚠ No Suggestion[/bold yellow]",
                border_style="yellow"
            ))
            console.print()

            if verbose:
                # Display diagnostic info for rejected sessions
                correction = result.get('correction_detected', 'unknown')
                dissatisfaction = result.get('dissatisfaction_level', 'unknown')
                console.print(f"[cyan]Correction Detected:[/cyan] {correction}")
                console.print(f"[cyan]Dissatisfaction Level:[/cyan] {dissatisfaction}")
                console.print()
                console.print("[cyan]Reasoning:[/cyan]")
                console.print(Markdown(result['reasoning']))

    except FileNotFoundError:
        console.print(f"[bold red]✗ Error: Transcript file not found: {transcript_path}[/bold red]")
        sys.exit(1)
    except json.JSONDecodeError as e:
        console.print(f"[bold red]✗ Error: Failed to parse Bedrock response as JSON: {e}[/bold red]")
        if verbose:
            console.print(f"[dim]Response may not be in expected format[/dim]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[bold red]✗ Error: {e}[/bold red]")
        if verbose:
            import traceback
            console.print("[dim]" + traceback.format_exc() + "[/dim]")
        sys.exit(1)

if __name__ == "__main__":
    main()
