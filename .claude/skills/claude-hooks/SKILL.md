---
name: claude-hooks
description: Claude Hooks allows to modify the flow of Claude code. This skill describes the use and how to modify these hooks
---


# Claude Hooks

## How to add a hook

Claude hooks are places in .claude/settings.json file. Below is an example:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "jq -r '\"\\(.tool_input.command) - \\(.tool_input.description // \"No description\")\"' >> ~/.claude/bash-command-log.txt"
          }
        ]
      }
    ]
  }
}
```

Matcher can be "*" if this is unknown at the time of writing.

## Types of hooks

- PreToolUse: Runs before tool calls (can block them)
- PostToolUse: Runs after tool calls complete
- UserPromptSubmit: Runs when the user submits a prompt, before Claude processes it
- Notification: Runs when Claude Code sends notifications
- Stop: Runs when Claude Code finishes responding
- SubagentStop: Runs when subagent tasks complete
- PreCompact: Runs before Claude Code is about to run a compact operation
- SessionStart: Runs when Claude Code starts a new session or resumes an existing session
- SessionEnd: Runs when Claude Code session ends

## Hook Event Data

All hooks receive JSON data via stdin. Below are examples of the data structure for each hook type.

### Common Fields

Most hooks include these common fields:
- `session_id` - Unique identifier for the session
- `transcript_path` - Path to the session transcript JSONL file
- `cwd` - Current working directory
- `hook_event_name` - Name of the hook event
- `permission_mode` - Current permission mode (when applicable)

### SessionStart

Triggered when Claude Code starts a new session or resumes an existing one.

```json
{
  "session_id": "abc12345-1234-5678-90ab-cdef12345678",
  "transcript_path": "/home/user/.claude/projects/-home-user-project/abc12345.jsonl",
  "cwd": "/home/user/project",
  "hook_event_name": "SessionStart",
  "source": "startup"
}
```

### SessionEnd

Triggered when Claude Code session ends.

```json
{
  "session_id": "abc12345-1234-5678-90ab-cdef12345678",
  "transcript_path": "/home/user/.claude/projects/-home-user-project/abc12345.jsonl",
  "cwd": "/home/user/project",
  "hook_event_name": "SessionEnd",
  "reason": "prompt_input_exit"
}
```

### UserPromptSubmit

Triggered when the user submits a prompt, before Claude processes it.

```json
{
  "session_id": "abc12345-1234-5678-90ab-cdef12345678",
  "transcript_path": "/home/user/.claude/projects/-home-user-project/abc12345.jsonl",
  "cwd": "/home/user/project",
  "permission_mode": "default",
  "hook_event_name": "UserPromptSubmit",
  "prompt": "Write a function to parse JSON"
}
```

### PreToolUse

Triggered before a tool is called. Can be used to block or modify tool calls.

```json
{
  "session_id": "abc12345-1234-5678-90ab-cdef12345678",
  "transcript_path": "/home/user/.claude/projects/-home-user-project/abc12345.jsonl",
  "cwd": "/home/user/project",
  "permission_mode": "default",
  "hook_event_name": "PreToolUse",
  "tool_name": "Read",
  "tool_input": {
    "file_path": "/home/user/project/src/main.py"
  }
}
```

Example with Bash tool:

```json
{
  "session_id": "abc12345-1234-5678-90ab-cdef12345678",
  "transcript_path": "/home/user/.claude/projects/-home-user-project/abc12345.jsonl",
  "cwd": "/home/user/project",
  "permission_mode": "default",
  "hook_event_name": "PreToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "git status",
    "description": "Check git repository status"
  }
}
```

### PostToolUse

Triggered after a tool completes execution.

```json
{
  "session_id": "abc12345-1234-5678-90ab-cdef12345678",
  "transcript_path": "/home/user/.claude/projects/-home-user-project/abc12345.jsonl",
  "cwd": "/home/user/project",
  "permission_mode": "default",
  "hook_event_name": "PostToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "git status",
    "description": "Check git repository status"
  },
  "tool_response": {
    "stdout": "On branch main\nnothing to commit, working tree clean\n",
    "stderr": "",
    "interrupted": false,
    "isImage": false
  }
}
```

Example with Read tool:

```json
{
  "session_id": "abc12345-1234-5678-90ab-cdef12345678",
  "transcript_path": "/home/user/.claude/projects/-home-user-project/abc12345.jsonl",
  "cwd": "/home/user/project",
  "permission_mode": "default",
  "hook_event_name": "PostToolUse",
  "tool_name": "Read",
  "tool_input": {
    "file_path": "/home/user/project/config.json"
  },
  "tool_response": {
    "type": "text",
    "file": {
      "filePath": "/home/user/project/config.json",
      "content": "{\n  \"version\": \"1.0.0\"\n}\n",
      "numLines": 3,
      "startLine": 1,
      "totalLines": 3
    }
  }
}
```

### SubagentStop

Triggered when a subagent task completes.

```json
{
  "session_id": "abc12345-1234-5678-90ab-cdef12345678",
  "transcript_path": "/home/user/.claude/projects/-home-user-project/abc12345.jsonl",
  "cwd": "/home/user/project",
  "permission_mode": "default",
  "hook_event_name": "SubagentStop",
  "stop_hook_active": false
}
```

### Stop

Triggered when Claude Code finishes responding to the user.

```json
{
  "session_id": "abc12345-1234-5678-90ab-cdef12345678",
  "transcript_path": "/home/user/.claude/projects/-home-user-project/abc12345.jsonl",
  "cwd": "/home/user/project",
  "permission_mode": "default",
  "hook_event_name": "Stop",
  "stop_hook_active": false
}
```

### Notification

Triggered when Claude Code sends a notification (not commonly triggered).

Expected structure (not yet observed):
```json
{
  "session_id": "abc12345-1234-5678-90ab-cdef12345678",
  "transcript_path": "/home/user/.claude/projects/-home-user-project/abc12345.jsonl",
  "cwd": "/home/user/project",
  "permission_mode": "default",
  "hook_event_name": "Notification",
  "notification": {
    "message": "Notification content"
  }
}
```

### PreCompact

Triggered before Claude Code runs a compact operation (not commonly triggered).

Expected structure (not yet observed):
```json
{
  "session_id": "abc12345-1234-5678-90ab-cdef12345678",
  "transcript_path": "/home/user/.claude/projects/-home-user-project/abc12345.jsonl",
  "cwd": "/home/user/project",
  "permission_mode": "default",
  "hook_event_name": "PreCompact"
}
```

## Hook Command Tips

When writing hook commands that process this JSON data:

1. **Use `jq` for JSON processing**: Parse and extract fields easily
   ```bash
   jq -r '.prompt' # Extract the prompt field
   jq -r '.tool_name' # Extract the tool name
   ```

2. **Log to files**: Use append mode to keep history
   ```bash
   cat >> ~/.claude/hook.log
   ```

3. **Handle errors gracefully**: Hooks should not break the workflow
   ```bash
   command 2>/dev/null || true
   ```

4. **Access nested fields**: Tool responses often have nested data
   ```bash
   jq -r '.tool_response.stdout' # Get stdout from bash commands
   jq -r '.tool_input.command' # Get the command being executed
   ```
