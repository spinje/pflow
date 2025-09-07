# Claude Code Node Examples

This document provides comprehensive examples for using the Claude Code agentic node in pflow workflows.

## Overview

The Claude Code node (`claude-code`) is a powerful "super node" that integrates with Claude's AI-assisted development capabilities. It features:
- Dynamic schema-driven output for structured responses
- Comprehensive development task execution
- Metadata capture (cost, duration, usage)
- Tool usage (Read, Write, Edit, Bash)
- Dual authentication support (API key or CLI)

## Basic Examples

### 1. Simple Code Generation (`claude-code-basic.json`)

Generate code with cost tracking:

```bash
pflow run examples/nodes/claude-code/claude-code-basic.json
```

**Features demonstrated:**
- Basic task execution
- Accessing generated text via `${node.result.text}`
- Cost tracking via `${node._claude_metadata.total_cost_usd}`
- Duration and token usage tracking

### 2. Structured Code Review (`claude-code-schema.json`)

Perform code review with structured JSON output:

```bash
pflow run examples/nodes/claude-code/claude-code-schema.json --file_path your_script.py
```

**Features demonstrated:**
- Schema-driven output with specific fields
- Structured data access via `${node.result.field_name}`
- Input parameters for dynamic workflows
- Multiple output files from single analysis

**Schema benefits:**
- Predictable output structure
- Type validation
- Direct field access without parsing
- Fallback to text if JSON parsing fails

### 3. Debugging Assistant (`claude-code-debug.json`)

Analyze errors and get debugging assistance:

```bash
pflow run examples/nodes/claude-code/claude-code-debug.json --error_message "TypeError: ..."
```

**Features demonstrated:**
- Error analysis with structured output
- Root cause analysis and solutions
- Confidence scoring
- Prevention tips

## Advanced Examples

### 4. Git Workflow Integration (`claude-code-git-workflow.json`)

Analyze git changes and generate PR descriptions:

```bash
pflow run examples/nodes/claude-code/claude-code-git-workflow.json
```

**Features demonstrated:**
- Integration with git nodes
- Multi-stage analysis pipeline
- Context passing between Claude calls
- Cost aggregation across multiple calls
- System prompts for specific personas

## Key Features

### Schema-Driven Output

When you provide an `output_schema`, Claude's response is automatically parsed into a structured dict:

```json
{
  "output_schema": {
    "summary": {"type": "str", "description": "Brief summary"},
    "score": {"type": "int", "description": "Score from 1-10"},
    "items": {"type": "list", "description": "List of items"}
  }
}
```

Access values directly:
- `${node.result.summary}`
- `${node.result.score}`
- `${node.result.items}`

### Metadata Access

Every execution captures valuable metadata in `_claude_metadata`:

```json
{
  "total_cost_usd": 0.165,        // Execution cost
  "duration_ms": 4805,            // Total duration
  "duration_api_ms": 3046,        // API call duration
  "num_turns": 2,                 // Actual turns used
  "session_id": "...",            // Session identifier
  "usage": {                      // Token usage details
    "input_tokens": 1234,
    "output_tokens": 567,
    "cache_read_input_tokens": 890
  }
}
```

Access in templates:
- `${node._claude_metadata.total_cost_usd}`
- `${node._claude_metadata.usage.input_tokens}`

### Context Parameter

Pass complex context as a dict:

```json
{
  "context": {
    "code": "${read_file.content}",
    "config": "${read_config.data}",
    "history": "${git_log.commits}"
  }
}
```

### Authentication Options

1. **API Key (Console billing)**:
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...
   pflow run workflow.json
   ```

2. **CLI Authentication (Pro/Max subscription)**:
   ```bash
   claude auth login
   pflow run workflow.json
   ```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `task` | Required | Development task description |
| `context` | None | Additional context (string or dict) |
| `output_schema` | None | JSON schema for structured output |
| `working_directory` | `os.getcwd()` | Project root directory |
| `model` | `claude-sonnet-4-20250514` | Claude model identifier |
| `allowed_tools` | `["Read", "Write", "Edit", "Bash"]` | Permitted tools |
| `max_turns` | 50 | Maximum conversation turns |
| `max_thinking_tokens` | 8000 | Maximum tokens for reasoning |
| `system_prompt` | None | System instructions for Claude |

## Best Practices

### 1. Use Schemas for Predictable Output
When you need specific data fields, always use `output_schema`:
```json
{
  "output_schema": {
    "field_name": {"type": "type", "description": "What this field contains"}
  }
}
```

### 2. Set Appropriate max_turns
- Simple tasks: `max_turns: 1`
- Code review: `max_turns: 2-3`
- Complex debugging: `max_turns: 5-10`

### 3. Track Costs
Always log costs for expensive operations:
```json
{
  "type": "echo",
  "params": {
    "message": "Cost: $${node._claude_metadata.total_cost_usd}"
  }
}
```

### 4. Use Context Wisely
Pass structured context for complex tasks:
```json
{
  "context": {
    "requirements": "...",
    "constraints": "...",
    "examples": "..."
  }
}
```

### 5. Handle Schema Failures
Check for `_schema_error` when using schemas:
```bash
# In a conditional node (future feature)
if ${node._schema_error}:
  echo "Failed to parse JSON, raw text available in ${node.result.text}"
```

## Error Handling

The node provides user-friendly error messages for common issues:
- CLI not installed → Installation instructions
- Authentication failed → Auth command guidance
- Rate limits → Retry suggestions
- Timeouts → Task complexity hints

## Performance Tips

1. **Minimize turns**: Each turn costs money and time
2. **Use specific prompts**: Clear instructions reduce iterations
3. **Cache when possible**: Reuse results across workflows
4. **Monitor costs**: Track `total_cost_usd` for budget management
5. **Set timeouts**: Default is 300s, adjust for long tasks

## Integration Patterns

### Code Quality Pipeline
```
read-file → claude-code (review) → write-file (report) → git-commit
```

### Documentation Generation
```
git-diff → claude-code (analyze) → claude-code (document) → write-file
```

### Test Generation
```
read-file (code) → claude-code (generate tests) → write-file (tests) → shell (run tests)
```

### Refactoring Workflow
```
read-file → claude-code (analyze) → claude-code (refactor) → write-file → git-diff
```

## Troubleshooting

**Issue**: "Claude not outputting JSON despite schema"
- **Solution**: Ensure `max_turns` > 1, as Claude may need multiple turns

**Issue**: "High costs"
- **Solution**: Reduce `max_turns`, use smaller context, batch operations

**Issue**: "Timeout errors"
- **Solution**: Break complex tasks into smaller steps, increase timeout

**Issue**: "Authentication failed"
- **Solution**: Check `claude doctor` or verify `ANTHROPIC_API_KEY`

## See Also

- [Claude Code SDK Documentation](https://github.com/anthropics/claude-code-sdk)
- [pflow Documentation](../../README.md)
- [Other Examples](../../README.md)