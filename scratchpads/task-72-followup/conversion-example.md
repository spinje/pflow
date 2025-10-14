# CLI to MCP Conversion Example

This shows a concrete before/after example of converting a section from CLI to MCP format.

## Before: CLI Version

```markdown
### 2. DISCOVER WORKFLOWS (5 minutes)

**Check for existing workflows before building new ones.**

This is MANDATORY - never skip this step. Users often don't know what workflows already exist.

```bash
uv run pflow workflow discover "user's request in natural language"
```

**What you get**: Matching workflows with names, descriptions, inputs/outputs, confidence scores, and reasoning.

#### Processing Discovery Results - Exact Decision Tree

| User Intent | Match Score | Required Params | Action |
|------------|-------------|-----------------|---------|
| "run/execute [workflow]" | ≥90% | All present | Execute immediately |
| "run/execute [workflow]" | ≥90% | Missing | Ask for params, then execute |

**Execute existing workflow**: Skip to execution

```bash
# Run the discovered workflow
uv run pflow --trace --no-repair workflow-name param1=value param2=value
```

### 3. DISCOVER NODES (3 minutes)

**Find the building blocks for your workflow (only if building new).**

```bash
uv run pflow registry discover "I need to fetch Slack messages, analyze with AI, send responses"
```

**Only use manual commands if AI discovery is unavailable**:
- `uv run pflow registry describe node1 node2` - Get specific node specs
- Avoid `uv run pflow registry list` - pollutes context

### 3.2. TEST MCP/HTTP NODES (Mandatory for MCP Workflows)

```bash
# Test each MCP node with realistic parameters:
uv run pflow registry run mcp-service-TOOL param="test-value" --show-structure
```

### 7. VALIDATE (2 minutes per iteration)

Catch structural errors before execution.

```bash
uv run pflow --validate-only workflow.json
```

### 10. SAVE (1 minute)

Save to global library for reuse:

```bash
uv run pflow workflow save .pflow/workflows/draft.json workflow-name "Description"

# With optional enhancements
uv run pflow workflow save draft.json workflow-name "Description" --generate-metadata --delete-draft
```

**Always tell the user how to run their saved workflow**:
```bash
# Show with user's actual values:
uv run pflow workflow-name channel=C123 sheet_id=abc123
```
```

---

## After: MCP Version

```markdown
### 2. DISCOVER WORKFLOWS (5 minutes)

**Check for existing workflows before building new ones.**

This is MANDATORY - never skip this step. Users often don't know what workflows already exist.

```python
workflow_discover(query="user's request in natural language")
```

**What you get**: Matching workflows with names, descriptions, inputs/outputs, confidence scores, and reasoning. Response is always JSON.

#### Processing Discovery Results - Exact Decision Tree

| User Intent | Match Score | Required Params | Action |
|------------|-------------|-----------------|---------|
| "run/execute [workflow]" | ≥90% | All present | Execute immediately |
| "run/execute [workflow]" | ≥90% | Missing | Ask for params, then execute |

**Execute existing workflow**: Skip to execution

```python
# Run the discovered workflow
# Note: MCP always saves traces and never auto-repairs (built-in defaults)
workflow_execute(
    workflow="workflow-name",
    parameters={
        "param1": "value",
        "param2": "value"
    }
)
```

### 3. DISCOVER NODES (3 minutes)

**Find the building blocks for your workflow (only if building new).**

```python
registry_discover(
    query="I need to fetch Slack messages, analyze with AI, send responses"
)
```

**Only use manual commands if AI discovery is unavailable**:
- `registry_describe(node_types=["node1", "node2"])` - Get specific node specs
- Avoid `registry_list()` - pollutes context (returns all 60+ nodes)

### 3.2. TEST MCP/HTTP NODES (Mandatory for MCP Workflows)

```python
# Test each MCP node with realistic parameters
# Note: show_structure is optional, defaults to false
registry_run(
    node_type="mcp-service-TOOL",
    parameters={"param": "test-value"},
    show_structure=True  # Reveals nested output structure
)
```

**MCP-specific tip**: The `result` field in the response always includes the actual output structure, making it easy to discover nested paths.

### 7. VALIDATE (2 minutes per iteration)

Catch structural errors before execution.

```python
workflow_validate(workflow="workflow.json")
# Or validate inline dict:
workflow_validate(workflow={"nodes": [...], "edges": [...]})
```

**MCP advantage**: You can validate workflow dicts without saving to files, enabling faster iteration.

### 10. SAVE (1 minute)

Save to global library for reuse:

```python
workflow_save(
    workflow=".pflow/workflows/draft.json",
    name="workflow-name",
    description="Description"
)

# With optional enhancements
workflow_save(
    workflow="draft.json",
    name="workflow-name",
    description="Description",
    generate_metadata=True,  # Optional: AI-generated metadata
    delete_draft=True        # Optional: Remove draft after save
)
```

**MCP advantage**: The response includes a `message` field with execution examples:

```json
{
  "success": true,
  "message": "Run with:\n  workflow-name channel=<string> sheet_id=<string>",
  "name": "workflow-name"
}
```

**Always tell the user how to run their saved workflow**:
```python
# Execute the saved workflow
workflow_execute(
    workflow="workflow-name",
    parameters={
        "channel": "C123",
        "sheet_id": "abc123"
    }
)
```
```

---

## Key Differences Highlighted

### 1. Command Syntax
- **Before**: `uv run pflow workflow discover "query"`
- **After**: `workflow_discover(query="query")`

### 2. Parameter Passing
- **Before**: `param1=value param2=value` (CLI args)
- **After**: `parameters={"param1": "value", "param2": "value"}` (JSON dict)

### 3. Flags → Built-in Behavior
- **Before**: `--trace --no-repair` (explicit flags)
- **After**: Comment explaining these are built-in defaults

### 4. Boolean Parameters
- **Before**: `--show-structure` (flag presence)
- **After**: `show_structure=True` (explicit parameter)

### 5. Language Changes
- **Before**: bash code blocks
- **After**: python code blocks (for tool call syntax)

### 6. Response Format
- **Before**: Text output (with optional `--json`)
- **After**: Always JSON (note this in explanations)

### 7. Flexibility Notes
- **After**: Add notes about dict support, inline workflows, session context

## What Stays the Same

1. ✅ **Conceptual structure**: The 10-step loop is identical
2. ✅ **Decision tables**: Logic is the same
3. ✅ **Timing estimates**: Still 5 minutes, 3 minutes, etc.
4. ✅ **Core advice**: "MANDATORY", "Test first", etc.
5. ✅ **Workflow IR examples**: JSON structure unchanged

## What Gets Added (MCP-Specific)

1. **Response format notes**: "Response is always JSON"
2. **Built-in behavior notes**: "MCP always saves traces"
3. **Advantages**: "You can validate dicts without files"
4. **Response structure examples**: Show the JSON agents receive

## Conversion Complexity Rating

- **Simple replacements**: 85% (command syntax, flags)
- **Context additions**: 10% (advantage notes, response examples)
- **Manual review**: 5% (edge cases, quality check)

**Overall: LOW complexity, HIGH automation potential**
