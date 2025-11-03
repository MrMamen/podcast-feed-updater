#!/usr/bin/env python3
import sys
import os
import json
from datetime import datetime

def format_timestamp(timestamp_str):
    """Convert ISO timestamp to readable format"""
    try:
        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M:%S UTC')
    except:
        return timestamp_str

def format_message_content(content):
    """Format message content in a readable way"""
    if isinstance(content, list):
        formatted_parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get('type') == 'text':
                    formatted_parts.append(part.get('text', ''))
                elif part.get('type') == 'thinking':
                    formatted_parts.append(f"[THINKING]\n{part.get('thinking', '')}\n[/THINKING]")
                else:
                    formatted_parts.append(f"[{part.get('type', 'unknown').upper()}]: {str(part)}")
            else:
                formatted_parts.append(str(part))
        return '\n'.join(formatted_parts)
    elif isinstance(content, str):
        return content
    else:
        return str(content)

def calculate_cost(model_name, input_tokens, output_tokens):
    """Calculate cost based on model and token usage"""
    # Pricing per million tokens (as of 2025)
    pricing = {
        'claude-sonnet-4': {'input': 3.00, 'output': 15.00},
        'claude-sonnet-3-5': {'input': 3.00, 'output': 15.00},
        'claude-opus-4': {'input': 15.00, 'output': 75.00},
        'claude-haiku-3-5': {'input': 0.80, 'output': 4.00},
        'claude-3-5-sonnet': {'input': 3.00, 'output': 15.00},
        'claude-3-opus': {'input': 15.00, 'output': 75.00},
        'claude-3-haiku': {'input': 0.25, 'output': 1.25},
    }

    # Try to match model name to pricing
    model_key = None
    model_lower = model_name.lower()
    for key in pricing.keys():
        if key in model_lower:
            model_key = key
            break

    if not model_key:
        # Default to Sonnet pricing if unknown
        model_key = 'claude-sonnet-3-5'

    rates = pricing[model_key]
    input_cost = (input_tokens / 1_000_000) * rates['input']
    output_cost = (output_tokens / 1_000_000) * rates['output']
    total_cost = input_cost + output_cost

    return {
        'input_cost': input_cost,
        'output_cost': output_cost,
        'total_cost': total_cost,
        'model_used': model_key
    }

def parse_transcript_to_readable(transcript_path):
    """Parse JSONL transcript file and convert to human-readable format"""
    if not os.path.exists(transcript_path):
        return None, f"Error: Transcript file not found at {transcript_path}"

    readable_content = []
    total_input_tokens = 0
    total_output_tokens = 0
    models_used = set()

    try:
        with open(transcript_path, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                    entry_type = entry.get('type', 'unknown')

                    if entry_type == 'file-history-snapshot':
                        readable_content.append(f"📸 FILE SNAPSHOT at {format_timestamp(entry.get('snapshot', {}).get('timestamp', ''))}")
                        readable_content.append("-" * 40)

                    elif entry_type == 'user':
                        timestamp = format_timestamp(entry.get('timestamp', ''))
                        message = entry.get('message', {})
                        content = message.get('content', '')

                        readable_content.append(f"👤 USER MESSAGE [{timestamp}]")
                        readable_content.append("-" * 40)
                        readable_content.append(format_message_content(content))
                        readable_content.append("")

                    elif entry_type == 'assistant':
                        timestamp = format_timestamp(entry.get('timestamp', ''))
                        message = entry.get('message', {})
                        content = message.get('content', [])
                        model = message.get('model', 'unknown')
                        models_used.add(model)

                        readable_content.append(f"🤖 ASSISTANT RESPONSE [{timestamp}] - Model: {model}")
                        readable_content.append("-" * 40)
                        readable_content.append(format_message_content(content))

                        # Add usage information if available
                        usage = message.get('usage', {})
                        if usage:
                            input_tokens = usage.get('input_tokens', 0)
                            output_tokens = usage.get('output_tokens', 0)
                            total_input_tokens += input_tokens
                            total_output_tokens += output_tokens
                        readable_content.append("")

                    else:
                        readable_content.append(f"📋 {entry_type.upper()} [{format_timestamp(entry.get('timestamp', ''))}]")
                        readable_content.append("-" * 40)
                        readable_content.append(json.dumps(entry, indent=2))
                        readable_content.append("")

                except json.JSONDecodeError as e:
                    readable_content.append(f"❌ Error parsing line {line_num}: {e}")
                    readable_content.append(f"Raw line: {line}")
                    readable_content.append("")

    except Exception as e:
        return None, f"Error reading transcript file: {e}"

    readable_content.append("=" * 80)
    readable_content.append("END OF TRANSCRIPT")
    readable_content.append("=" * 80)

    # Calculate cost for primary model
    cost_info = None
    if models_used and total_input_tokens > 0:
        primary_model = list(models_used)[0]  # Use first model found
        cost_info = calculate_cost(primary_model, total_input_tokens, total_output_tokens)

    return {
        'content': '\n'.join(readable_content),
        'total_input_tokens': total_input_tokens,
        'total_output_tokens': total_output_tokens,
        'models_used': list(models_used),
        'cost_info': cost_info
    }, None

# Create .transcripts directory if it doesn't exist
os.makedirs('.transcripts', exist_ok=True)

# Read JSON from stdin
json_input = sys.stdin.read()

try:
    # Parse the JSON input
    data = json.loads(json_input)

    # Extract variables
    session_id = data.get('session_id')
    transcript_path = data.get('transcript_path')
    cwd = data.get('cwd')
    hook_event_name = data.get('hook_event_name')
    reason = data.get('reason')

    # Print extracted variables
    print(f"Session ID: {session_id}")
    print(f"Transcript Path: {transcript_path}")
    print(f"Current Working Directory: {cwd}")
    print(f"Hook Event Name: {hook_event_name}")
    print(f"Reason: {reason}")

    # Generate timestamp for filename
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_filename = f".transcripts/session_{timestamp}_{session_id[:8]}.txt"

    # Process transcript file if available
    if transcript_path and os.path.exists(transcript_path):
        print(f"\n📖 Processing transcript file...")
        result, error = parse_transcript_to_readable(transcript_path)

        if error:
            print(f"❌ {error}")
        else:
            # Write readable transcript to timestamped file
            with open(output_filename, 'w', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write("SESSION SUMMARY\n")
                f.write("=" * 80 + "\n\n")

                # Cost Summary
                if result['cost_info']:
                    cost = result['cost_info']
                    f.write("💰 COST SUMMARY\n")
                    f.write("-" * 40 + "\n")
                    f.write(f"Model: {cost['model_used']}\n")
                    f.write(f"Input Tokens:  {result['total_input_tokens']:,} (${cost['input_cost']:.4f})\n")
                    f.write(f"Output Tokens: {result['total_output_tokens']:,} (${cost['output_cost']:.4f})\n")
                    f.write(f"Total Cost: ${cost['total_cost']:.4f}\n\n")
                else:
                    f.write("💰 COST SUMMARY\n")
                    f.write("-" * 40 + "\n")
                    f.write("No token usage data available\n\n")

                # Session Information
                f.write("📋 SESSION INFORMATION\n")
                f.write("-" * 40 + "\n")
                f.write(f"Session ID: {session_id}\n")
                f.write(f"Working Directory: {cwd}\n")
                f.write(f"Hook Event: {hook_event_name}\n")
                f.write(f"End Reason: {reason}\n")
                f.write(f"Models Used: {', '.join(result['models_used'])}\n")
                f.write(f"Original Transcript Path: {transcript_path}\n")
                f.write(f"Processed on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("\n\n")
                f.write(result['content'])

            print(f"✅ Human-readable transcript saved to: {output_filename}")
            if result['cost_info']:
                print(f"💰 Session cost: ${result['cost_info']['total_cost']:.4f}")
    else:
        print(f"❌ Transcript file not found at: {transcript_path}")

    # Run the review-transcript tool to analyze the session
    print(f"\n🔍 Analyzing transcript with Bedrock...")
    import subprocess

    # Ensure .memories directory exists
    os.makedirs('.memories', exist_ok=True)

    # Determine memory output filename in .memories directory (JSON format)
    memory_filename = f".memories/memory_{timestamp}_{session_id[:8]}.json"

    try:
        # Run the review-transcript tool with UV
        result = subprocess.run(
            ['uv', 'run', 'scripts/generate-memory-from-transcript.py', output_filename, '-o', memory_filename, '-v'],
            check=False,
            capture_output=False,
            text=True
        )

        if result.returncode == 0:
            print(f"✅ Analysis complete!")
            if os.path.exists(memory_filename):
                print(f"📝 Memory suggestion saved to: {memory_filename}")
        else:
            print(f"⚠️  Analysis completed with status code: {result.returncode}")

    except FileNotFoundError:
        print("❌ Error: 'uv' command not found. Is UV installed?")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error running transcript review: {e}")
        sys.exit(1)

except json.JSONDecodeError as e:
    print(f"Error parsing JSON: {e}")
    # Fallback: write raw input to log file
    with open('.claude/log.txt', 'w') as f:
        f.write(f"Failed to parse JSON: {e}\n")
        f.write(f"Raw input:\n{json_input}\n")
except KeyboardInterrupt:
    print("\nExiting...")
    sys.exit(0)
except Exception as e:
    print(f"Unexpected error: {e}")
    sys.exit(1)