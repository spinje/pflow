# The 10% That Can't Be Automated

## Category 1: Conceptual Enhancements (5%)

These require human judgment about what information MCP agents need that CLI users don't.

### 1.1 MCP Advantage Explanations

**Example locations:**
- After discovery commands: "Response is always JSON"
- After validation: "You can validate dicts without saving to files"
- After registry_run: "The result field always includes structure info"

**Why not automatable:**
- Requires understanding of what makes MCP better
- Context-dependent - not every command needs a note
- Needs to explain the "why" not just the "what"

**Example manual addition:**
```markdown
# Before (automated):
registry_run(node_type="mcp-slack-FETCH", parameters={...})

# After (manual enhancement):
registry_run(node_type="mcp-slack-FETCH", parameters={...})

**MCP advantage**: Unlike CLI which requires `--show-structure` flag,
MCP always includes the full output structure in the response, making
it easy to discover nested paths like `result.data.messages[0].text`
```

### 1.2 Response Structure Examples

**Example locations:**
- After workflow_save: Show the JSON response with execution hints
- After workflow_execute: Show success vs error response format
- After registry_discover: Show the node spec structure

**Why not automatable:**
- Need to choose representative examples
- Should show most useful fields (not all)
- Context varies by section

**Example manual addition:**
```markdown
# Automated conversion:
workflow_save(workflow="file.json", name="my-workflow", description="...")

# Manual addition - show response structure:
**Response format:**
```json
{
  "success": true,
  "name": "my-workflow",
  "message": "Run with:\n  my-workflow channel=<string> limit=<number>",
  "path": "~/.pflow/workflows/my-workflow.json"
}
```
```

### 1.3 Built-in Behavior Notes

**Why manual:**
- Need to explain what flags do (not just remove them)
- Should add these at first mention only
- Requires understanding of flag purpose

**Example:**
```markdown
# CLI version:
uv run pflow --trace workflow.json

# Automated conversion:
workflow_execute(workflow="workflow.json", parameters={...})

# Manual enhancement:
workflow_execute(workflow="workflow.json", parameters={...})
# Note: Traces are always saved to ~/.pflow/debug/ (no flag needed)

# OR add as callout box:
> **MCP Built-in Behavior**: All executions automatically save traces to
> `~/.pflow/debug/workflow-trace-*.json`. The CLI requires `--trace` flag,
> but MCP does this by default for better debugging.
```

## Category 2: New Content Sections (3%)

Entirely new sections that don't exist in CLI version.

### 2.1 MCP Introduction Section

**What to add:**
```markdown
## About This Guide

This guide is optimized for AI agents using the **pflow MCP server**.

### Key MCP Advantages

1. **Structured Responses**: All tools return JSON (no text parsing)
2. **Built-in Defaults**: Traces always saved, no auto-repair
3. **Flexible Input**: Workflows can be dicts, names, or paths
4. **Session Context**: MCP can maintain state across calls
5. **Better Errors**: Full context in structured format

### Quick Reference: CLI vs MCP

| CLI | MCP |
|-----|-----|
| `uv run pflow workflow discover` | `workflow_discover()` |
| Text output (+ optional --json) | Always JSON |
| File-based workflows | Dicts, names, OR files |
```

**Why manual:**
- Needs overall framing for MCP users
- Requires understanding of target audience (agents vs humans)
- Sets expectations for rest of document

### 2.2 MCP-Specific Patterns Section

**What to add:**
```markdown
## MCP-Specific Patterns

### Pattern: Inline Workflow Development

MCP agents can iterate without file I/O:

```python
# 1. Build workflow as dict
workflow = {
    "nodes": [...],
    "edges": [...],
    "inputs": {...}
}

# 2. Validate inline
result = workflow_validate(workflow=workflow)

# 3. Fix errors if needed
if not result["valid"]:
    workflow = fix_template(workflow, result["errors"])
    result = workflow_validate(workflow=workflow)

# 4. Execute when ready
workflow_execute(workflow=workflow, parameters={...})
```

### Pattern: Discovery → Build → Test Loop

```python
# Discovery phase (cache results)
workflows = workflow_discover(query="user request")
nodes = registry_discover(query="slack and AI")

# Build phase (use cached info)
workflow = construct_from_specs(nodes)

# Test phase (iterate fast)
for iteration in range(3):
    result = workflow_validate(workflow=workflow)
    if result["valid"]:
        break
    workflow = fix_errors(workflow, result["errors"])
```
```

**Why manual:**
- Requires understanding of how agents use MCP differently
- Shows patterns not possible with CLI
- Needs code examples that demonstrate MCP advantages

### 2.3 Session Context Section

**What to add:**
```markdown
## MCP Session Context

Unlike CLI (stateless), MCP servers can maintain context:

**Use cases:**
1. Cache discovery results across multiple builds
2. Remember user preferences (model choice, output format)
3. Track workflow iterations for debugging
4. Maintain conversation history

**Example:**
```python
# First call: User says "build workflow for Slack"
nodes = registry_discover(query="slack operations")
# Agent stores: session.cached_nodes = nodes

# Later: User says "add GitHub too"
# Agent uses: session.cached_nodes (Slack) + new GitHub nodes
# No need to re-discover Slack nodes
```
```

**Why manual:**
- Concept doesn't exist in CLI version
- Requires architectural understanding
- Shows unique MCP capabilities

## Category 3: Edge Cases & Complex Commands (2%)

Patterns that are too complex or rare to automate reliably.

### 3.1 Multi-line Commands

**CLI version:**
```bash
uv run pflow workflow save \
  .pflow/workflows/long-name.json \
  my-workflow \
  "A very long description that spans multiple lines" \
  --generate-metadata \
  --delete-draft
```

**Why hard to automate:**
- Line continuation detection
- Multi-line string handling
- Multiple flags with different conversion rules

**Manual conversion:**
```python
workflow_save(
    workflow=".pflow/workflows/long-name.json",
    name="my-workflow",
    description="A very long description that spans multiple lines",
    generate_metadata=True,
    delete_draft=True
)
```

### 3.2 Commands with Shell Interpolation

**CLI version:**
```bash
# With environment variables
uv run pflow workflow-name api_token="$SLACK_TOKEN"

# With command substitution
uv run pflow workflow-name date="$(date +%Y-%m-%d)"
```

**Why hard to automate:**
- Shell variable syntax varies
- Need to explain how MCP handles this differently
- Context-dependent (some vars should be literals)

**Manual conversion:**
```python
# MCP handles environment variables automatically
workflow_execute(
    workflow="workflow-name",
    parameters={
        "api_token": "${SLACK_TOKEN}",  # MCP resolves from env
        "date": "2024-01-15"  # Or use datetime in agent code
    }
)

# Note: MCP can access environment variables by name,
# no shell interpolation needed
```

### 3.3 Complex Parameter Lists

**CLI version:**
```bash
uv run pflow registry run mcp-node \
  param1="simple" \
  param2='{"nested": "json"}' \
  param3="value with spaces" \
  --show-structure
```

**Why hard to automate:**
- Mixed quoting styles
- Embedded JSON strings
- Space handling rules differ

**Manual conversion:**
```python
registry_run(
    node_type="mcp-node",
    parameters={
        "param1": "simple",
        "param2": {"nested": "json"},  # Parse JSON strings
        "param3": "value with spaces"  # No escaping needed
    },
    show_structure=True
)
```

### 3.4 Conditional Examples

**CLI version:**
```markdown
**If tests fail:**
1. Explain the error
2. Help set up auth
3. DON'T proceed until fixed
```

**Why needs manual review:**
- Conceptual flow, not commands
- Need to verify logic still applies to MCP
- May need MCP-specific advice

**Manual enhancement:**
```markdown
**If tests fail:**
1. Explain the error - MCP errors include full context
2. Help set up auth - use `settings_set(key="TOKEN", value="...")`
3. DON'T proceed until fixed - validation errors are structured

**MCP tip**: Check `result["errors"]` array for detailed validation info
```

## Category 4: Quality & Consistency (1%)

Human verification to ensure conversion quality.

### 4.1 Terminology Consistency

**Check for:**
- "Execute workflow" vs "Run workflow" (pick one)
- "Parameters" vs "Params" (MCP uses parameters)
- "Tool call" vs "Function call" (prefer tool call)
- "Response" vs "Result" vs "Output" (pick one per context)

### 4.2 Example Verification

**Verify:**
- All code examples have matching input/output
- Response JSON matches actual MCP tool output
- Parameter names match registry specs
- Workflow IR examples are valid

### 4.3 Link Updates

**Update:**
- Internal section references (line numbers change)
- Navigation paths ("see Section X")
- Anchor links in tables

### 4.4 Formatting Consistency

**Check:**
- Code block language tags (python not bash)
- Callout box formatting
- Table alignment
- List indentation

## Summary: What Requires Manual Work

| Category | % of Effort | Examples | Why Not Automatable |
|----------|-------------|----------|---------------------|
| **Conceptual Enhancements** | 5% | Advantage notes, response examples | Requires judgment about what to explain |
| **New Content Sections** | 3% | MCP intro, patterns, session context | Doesn't exist in CLI version |
| **Edge Cases** | 2% | Multi-line commands, shell variables | Too complex to parse reliably |
| **Quality & Consistency** | 1% | Terminology, links, formatting | Requires human review |
| **Total Manual** | **11%** | | |

## Time Estimates

**For 2330-line AGENT_INSTRUCTIONS.md:**

- **Automated conversion**: 1 minute (script execution)
- **Category 1 (Conceptual)**: 2-3 hours (~30 locations × 5 minutes)
- **Category 2 (New content)**: 2-3 hours (write new sections)
- **Category 3 (Edge cases)**: 1-2 hours (10-15 complex commands)
- **Category 4 (Quality)**: 1 hour (review pass)

**Total manual work: 6-9 hours**

Compare to:
- **Full manual rewrite**: 20-30 hours
- **Savings from automation**: 14-21 hours (60-70% time reduction)

## Recommendation

**Prioritize the manual work:**

1. **Must do** (7 hours):
   - Category 1: Advantage notes at key decision points
   - Category 2: MCP introduction and inline workflow pattern
   - Category 4: Quality review

2. **Should do** (2 hours):
   - Category 3: Complex command conversions
   - Category 2: Session context section (if relevant)

3. **Nice to have** (1 hour):
   - Additional response structure examples
   - More MCP-specific patterns
   - Extended comparison tables

**The automated 90% gives you the foundation. The manual 10% gives you the polish and MCP-specific value.**
