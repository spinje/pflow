# Output Node Feature Proposal

## Overview

This document proposes adding an explicit output node (`stdout`) to make workflow output intentional and predictable, following Unix philosophy.

## Problem Statement

Currently:
- Workflows might output nothing (surprising to users)
- Output depends on magic key detection (`response` > `output` > `result` > `text`)
- Users need to know about `--output-key` flag
- Workflows don't compose well with pipes

## Proposed Solution

Add a simple `stdout` node that explicitly outputs content:

```json
{
  "id": "output",
  "type": "stdout",
  "params": {
    "content": "$analyze.response"
  }
}
```

## Benefits

1. **Explicit over implicit** - See exactly what gets output
2. **Composable** - Natural for Unix pipes
3. **Flexible** - Format output for humans or machines
4. **Simple** - One node, one responsibility

## Implementation Impact

### On Planner (Task 17)
The planner would add output nodes based on user intent:
- "get/fetch X" → Output the data
- "analyze/summarize X" → Output the analysis
- "create/fix X" → Output result/confirmation

### New Node Implementation
Create `src/pflow/nodes/io/stdout.py` with:
- Input: `content` (supports template variables)
- Parameters: `format` (text/json/yaml), `stream` (stdout/stderr)

### Example Workflows

```json
// "Get github issue 123"
{
  "nodes": [
    {"id": "get", "type": "github-get-issue", "params": {"issue": "123"}},
    {"id": "show", "type": "stdout", "params": {"content": "$get.issue_data"}}
  ]
}

// "Analyze errors" (with formatting)
{
  "nodes": [
    {"id": "analyze", "type": "llm", "params": {"prompt": "Analyze: $stdin"}},
    {"id": "output", "type": "stdout", "params": {
      "content": "# Error Analysis\\n\\n$analyze.response",
      "format": "text"
    }}
  ]
}
```

## Timeline

This feature can be implemented:
1. After Task 17 (planner) is complete
2. As a standalone node addition
3. With a planner enhancement to auto-add output nodes

## Open Questions

1. Should we also have `stderr` as a separate node or parameter?
2. Should output nodes support structured data formatting (tables, etc.)?
3. How do we handle binary data output?

## Related Documents

- Shell Integration Context (Task 8)
- Natural Language Planner (Task 17)
