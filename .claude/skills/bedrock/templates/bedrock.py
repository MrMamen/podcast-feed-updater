#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "click",
#     "rich",
#     "boto3",
#     "python-dotenv",
# ]
# ///

import click
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
import sys
import json
import os
from typing import Optional, Dict, Any
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

console = Console()

class BedrockClaudeClient:
    """Client for interacting with Claude Sonnet 4 via AWS Bedrock."""

    def __init__(self, region: str = "eu-south-2"):
        self.region = region
        self.model_id = "eu.anthropic.claude-sonnet-4-20250514-v1:0"  # Claude 4
        self.client = None

    def _initialize_client(self):
        """Initialize the Bedrock client with error handling."""
        try:
            self.client = boto3.client(
                'bedrock-runtime',
                region_name=self.region,
                aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
                aws_session_token=os.getenv('AWS_SESSION_TOKEN')  # For temporary credentials
            )
        except NoCredentialsError:
            raise Exception("AWS credentials not found. Please configure your AWS credentials.")
        except Exception as e:
            raise Exception(f"Failed to initialize Bedrock client: {str(e)}")

    def send_message(self, prompt: str, max_tokens: int = 4096, temperature: float = 0.7, system_prompt: Optional[str] = None) -> str:
        """Send a message to Claude Sonnet 4 and return the response."""
        if not self.client:
            self._initialize_client()

        # Construct the request body for Claude
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }

        # Add system prompt if provided
        if system_prompt:
            body["system"] = system_prompt

        try:
            response = self.client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(body),
                contentType='application/json'
            )

            # Parse the response
            response_body = json.loads(response['body'].read())

            if 'content' in response_body and len(response_body['content']) > 0:
                return response_body['content'][0]['text']
            else:
                raise Exception("No content in response")

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            raise Exception(f"Bedrock API error ({error_code}): {error_message}")
        except Exception as e:
            raise Exception(f"Failed to send message: {str(e)}")

    def send_message_with_structured_response(self, prompt: str, tool_name: str, tool_description: str, input_schema: Dict[str, Any], max_tokens: int = 4096, temperature: float = 0.1, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """Send a message to Claude and get a structured response using tool calling."""
        if not self.client:
            self._initialize_client()

        # Define the tool with the provided schema
        tool_definition = {
            "toolSpec": {
                "name": tool_name,
                "description": tool_description,
                "inputSchema": {
                    "json": input_schema
                }
            }
        }

        # Define the message
        message = {
            "role": "user",
            "content": [
                {"text": prompt}
            ]
        }

        # Build the converse request
        converse_params = {
            "modelId": self.model_id,
            "messages": [message],
            "toolConfig": {
                "tools": [tool_definition],
                "toolChoice": {"tool": {"name": tool_name}}
            },
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": temperature
            }
        }

        # Add system prompt if provided
        if system_prompt:
            converse_params["system"] = [{"text": system_prompt}]

        try:
            response = self.client.converse(**converse_params)

            # Extract and return the structured response
            if response.get('output', {}).get('message', {}).get('content'):
                for content_block in response['output']['message']['content']:
                    if content_block.get('toolUse'):
                        tool_use = content_block['toolUse']
                        if tool_use['name'] == tool_name:
                            return tool_use['input']

            raise Exception("No structured response found in the model output")

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            raise Exception(f"Bedrock API error ({error_code}): {error_message}")
        except Exception as e:
            raise Exception(f"Failed to send structured message: {str(e)}")

def load_prompt_from_file(file_path: str) -> str:
    """Load prompt from a file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        raise Exception(f"File not found: {file_path}")
    except Exception as e:
        raise Exception(f"Error reading file {file_path}: {str(e)}")

def load_json_schema_from_file(file_path: str) -> Dict[str, Any]:
    """Load JSON schema from a file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        raise Exception(f"Schema file not found: {file_path}")
    except json.JSONDecodeError as e:
        raise Exception(f"Invalid JSON in schema file {file_path}: {str(e)}")
    except Exception as e:
        raise Exception(f"Error reading schema file {file_path}: {str(e)}")

@click.command()
@click.option('--prompt', '-p', help='Prompt text to send to Claude')
@click.option('--file', '-f', help='File containing the prompt text')
@click.option('--system', '-s', help='System prompt text')
@click.option('--system-file', help='File containing the system prompt text')
@click.option('--structured', is_flag=True, help='Use structured response mode')
@click.option('--tool-name', default='structured_response', help='Name for the structured response tool (default: structured_response)')
@click.option('--tool-description', help='Description for the structured response tool')
@click.option('--schema-file', help='JSON file containing the input schema for structured response')
@click.option('--max-tokens', '-t', default=4096, help='Maximum tokens in response (default: 4096)')
@click.option('--temperature', default=0.7, help='Temperature for response generation (default: 0.7)')
@click.option('--region', '-r', default='eu-south-2', help='AWS region (default: eu-south-2)')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def main(prompt: Optional[str], file: Optional[str], system: Optional[str], system_file: Optional[str], structured: bool, tool_name: str, tool_description: Optional[str], schema_file: Optional[str], max_tokens: int, temperature: float, region: str, verbose: bool):
    """
    Send prompts to Claude Sonnet 4 via AWS Bedrock.

    This tool allows you to interact with Claude Sonnet 4 using AWS Bedrock.
    You can provide prompts directly via command line or load them from files.
    System prompts can be used to provide context and instructions.
    Structured response mode forces the model to respond with a specific JSON format.

    Examples:
        # Direct prompt
        uv run bedrock_claude.py -p "Explain quantum computing"

        # From file
        uv run bedrock_claude.py -f prompt.txt

        # With system prompt
        uv run bedrock_claude.py -p "Write a story" -s "You are a creative writer specializing in sci-fi"

        # With system prompt from file
        uv run bedrock_claude.py -p "Analyze this code" --system-file system_prompt.txt

        # Structured response
        uv run bedrock_claude.py -p "Analyze this feedback: 'Great product but slow shipping'" --structured --tool-description "Extract sentiment and issues" --schema-file schema.json

        # With custom parameters
        uv run bedrock_claude.py -p "Write a poem" --max-tokens 1000 --temperature 0.9

    AWS Credentials:
        Set AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and optionally AWS_SESSION_TOKEN
        environment variables, or use AWS CLI configuration.
    """
    try:
        # Validate input
        if not prompt and not file:
            console.print("[bold red]✗ Error: Either --prompt or --file must be provided[/bold red]")
            sys.exit(1)

        if prompt and file:
            console.print("[bold red]✗ Error: Cannot use both --prompt and --file options[/bold red]")
            sys.exit(1)

        if system and system_file:
            console.print("[bold red]✗ Error: Cannot use both --system and --system-file options[/bold red]")
            sys.exit(1)

        if structured and not schema_file:
            console.print("[bold red]✗ Error: --schema-file is required when using --structured mode[/bold red]")
            sys.exit(1)

        if structured and not tool_description:
            console.print("[bold red]✗ Error: --tool-description is required when using --structured mode[/bold red]")
            sys.exit(1)

        # Load prompt
        if file:
            if verbose:
                console.print(f"[dim]Loading prompt from file: {file}[/dim]")
            prompt = load_prompt_from_file(file)

        # Load system prompt
        system_prompt = None
        if system_file:
            if verbose:
                console.print(f"[dim]Loading system prompt from file: {system_file}[/dim]")
            system_prompt = load_prompt_from_file(system_file)
        elif system:
            system_prompt = system

        # Load schema for structured response
        input_schema = None
        if structured:
            if verbose:
                console.print(f"[dim]Loading schema from file: {schema_file}[/dim]")
            input_schema = load_json_schema_from_file(schema_file)

        if verbose:
            console.print(f"[dim]Region: {region}[/dim]")
            console.print(f"[dim]Max tokens: {max_tokens}[/dim]")
            console.print(f"[dim]Temperature: {temperature}[/dim]")
            console.print(f"[dim]Prompt length: {len(prompt)} characters[/dim]")
            if system_prompt:
                console.print(f"[dim]System prompt length: {len(system_prompt)} characters[/dim]")
            if structured:
                console.print(f"[dim]Structured mode: {tool_name}[/dim]")
                console.print(f"[dim]Tool description: {tool_description}[/dim]")

        # Initialize client and send message
        client = BedrockClaudeClient(region=region)

        if verbose:
            console.print("[dim]Sending request to Claude Sonnet 4...[/dim]")

        if structured:
            # Use structured response mode
            response = client.send_message_with_structured_response(
                prompt=prompt,
                tool_name=tool_name,
                tool_description=tool_description,
                input_schema=input_schema,
                max_tokens=max_tokens,
                temperature=temperature,
                system_prompt=system_prompt
            )

            # Display structured response
            console.print("\n" + "="*80)
            console.print(Panel(
                Text(json.dumps(response, indent=2)),
                title="[bold blue]Claude Sonnet 4 Structured Response[/bold blue]",
                border_style="blue"
            ))

            if verbose:
                console.print(f"\n[dim]Response fields: {len(response)} items[/dim]")
        else:
            # Use regular response mode
            response = client.send_message(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                system_prompt=system_prompt
            )

            # Display response
            console.print("\n" + "="*80)
            console.print(Panel(
                Text(response),
                title="[bold blue]Claude Sonnet 4 Response[/bold blue]",
                border_style="blue"
            ))

            if verbose:
                console.print(f"\n[dim]Response length: {len(response)} characters[/dim]")

        console.print("\n[bold green]✓ Success[/bold green]")

    except Exception as e:
        console.print(f"[bold red]✗ Error: {e}[/bold red]")
        sys.exit(1)

# Library interface for use in other scripts
def send_to_claude(prompt: str, region: str = "eu-south-2", max_tokens: int = 4096, temperature: float = 0.7, system_prompt: Optional[str] = None) -> str:
    """
    Library function to send a prompt to Claude Sonnet 4.

    Args:
        prompt: The text prompt to send
        region: AWS region (default: eu-south-2)
        max_tokens: Maximum tokens in response (default: 4096)
        temperature: Temperature for generation (default: 0.7)
        system_prompt: Optional system prompt to provide context

    Returns:
        The response text from Claude

    Raises:
        Exception: If the request fails
    """
    client = BedrockClaudeClient(region=region)
    return client.send_message(prompt, max_tokens, temperature, system_prompt)

def send_to_claude_structured(prompt: str, tool_name: str, tool_description: str, input_schema: Dict[str, Any], region: str = "eu-south-2", max_tokens: int = 4096, temperature: float = 0.1, system_prompt: Optional[str] = None) -> Dict[str, Any]:
    """
    Library function to send a prompt to Claude Sonnet 4 and get a structured response.

    Args:
        prompt: The text prompt to send
        tool_name: Name for the structured response tool
        tool_description: Description for the structured response tool
        input_schema: JSON schema defining the expected response structure
        region: AWS region (default: eu-south-2)
        max_tokens: Maximum tokens in response (default: 4096)
        temperature: Temperature for generation (default: 0.1)
        system_prompt: Optional system prompt to provide context

    Returns:
        The structured response as a dictionary

    Raises:
        Exception: If the request fails
    """
    client = BedrockClaudeClient(region=region)
    return client.send_message_with_structured_response(prompt, tool_name, tool_description, input_schema, max_tokens, temperature, system_prompt)

if __name__ == "__main__":
    main()