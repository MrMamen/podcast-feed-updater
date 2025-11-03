# Create Sub Agent

Create a new specialized sub agent for Claude Code with proper configuration and documentation.

## Instructions

This command creates a new sub agent in the `.claude/agents/` directory following the established format and best practices.

### Usage

When asked to create a sub agent, gather the following information:
- **Agent name** (kebab-case, e.g., "data-analyzer", "code-reviewer")
- **Description** (brief one-line summary of the agent's purpose)
- **Tools** (comma-separated list of tools the agent should have access to)
- **Specialized domain** (the agent's area of expertise)

### Agent Creation Process

1. **Create the agent file** in `.claude/agents/[agent-name].md`
2. **Use the standard frontmatter format**:
   ```yaml
   ---
   name: agent-name
   description: Brief description of the agent's purpose
   tools: Tool1, Tool2, Tool3
   ---
   ```
3. **Write detailed agent instructions** covering:
   - Core capabilities and expertise
   - Working methodology and approach
   - Best practices and standards
   - Expected output format
   - Domain-specific knowledge

### Template Structure

```markdown
---
name: [agent-name]
description: [One-line description of agent purpose]
tools: [Comma-separated list of tools]
---

You are an expert [domain] agent specialized in [specific area]. Your primary role is to [main purpose].

## Core Capabilities

[List 3-5 key capabilities with brief descriptions]

## Implementation Approach

When [working on tasks]:

- [Key methodology point 1]
- [Key methodology point 2]
- [Key methodology point 3]

## [Domain] Standards

[Relevant standards, criteria, or frameworks for this domain]

## Best Practices

- [Best practice 1]
- [Best practice 2]
- [Best practice 3]

Focus on [key focus area] and provide [expected output type].
```

### Common Tool Categories

**Research & Analysis:**
- Read, Grep, Glob, WebFetch

**Code Development:**
- Read, Write, Edit, MultiEdit, Bash

**Documentation:**
- Read, Write, Edit, MultiEdit

**System Operations:**
- Bash, Read, LS

**All Tools:**
- Use "*" for general-purpose agents that need access to all available tools

### Verification Checklist

Before completing, ensure:
- [ ] Frontmatter follows exact format with name, description, and tools
- [ ] Agent name uses kebab-case consistently
- [ ] Description is concise and specific
- [ ] Tool list matches the agent's intended capabilities
- [ ] Instructions are detailed and domain-specific
- [ ] Best practices section provides actionable guidance
- [ ] Agent has clear scope and purpose

### Examples of Good Agent Types

- **security-auditor**: Specialized in code security analysis and vulnerability detection
- **api-designer**: Expert in REST API design and documentation
- **performance-optimizer**: Focused on code performance analysis and optimization
- **test-writer**: Specialized in writing comprehensive test suites
- **documentation-writer**: Expert in technical documentation and user guides

## Success Criteria

✅ Agent file created in `.claude/agents/` directory
✅ Proper frontmatter with all required fields
✅ Detailed instructions tailored to the domain
✅ Clear scope and capabilities defined
✅ Appropriate tool selection for the agent's purpose