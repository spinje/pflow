# MCP Server Tools

**Purpose**: MCP tools are the public API for AI agents (Claude Desktop, Continue, etc.). Tool docstrings and parameter descriptions are directly visible to LLMs — they ARE the interface documentation.

## Architecture

**Tools are thin async wrappers** around services. Never put business logic in tools.

```python
@mcp.tool()
async def tool_name(param: Annotated[Type, Field(description="...")]) -> str:
    """Docstring visible to LLMs."""
    def _sync_operation():
        return Service.method(param)  # Delegate to service
    return await asyncio.to_thread(_sync_operation)
```

See `mcp_server/CLAUDE.md` for the async/sync bridge pattern explanation.

## Docstring Rules (LLMs See This)

### Parameter Descriptions
```python
Field(description="Role/purpose of parameter")  # ✓ Clear, concise
Field(description="Input parameters as key-value pairs")  # ✓ Format explained

Field(description="Parameters dict")  # ✗ Too vague
Field(description="List of node IDs to describe")  # ✗ Redundant (type is obvious)
```

### Examples Section
**Show ALL parameter variants**:
```python
Examples:
    # Variant 1: Simple case
    param="value"

    # Variant 2: Complex structure (use {...} placeholders)
    param={"inputs": {...}, "nodes": [...], "edges": [...]}

    # Variant 3: With context comment
    param="other-format"  # When to use this
```

**Always generic**:
- ✓ `"my-workflow"`, `"node-type"`, `"keyword"`
- ✓ `{"param": "value"}`, `{...}`, `[...]`
- ✗ `"pr-analyzer"`, `"github-create-issue"` (looks real, but arbitrary)

**Include output context**:
```python
# Search for nodes (returns matching nodes in table format)
pattern="keyword"
```

### Structure
```python
"""One-line summary.

Extended description with key behaviors.

IMPORTANT: Critical usage notes (for discovery tools: pass full user requests).

Examples:
    # Comment explaining variant
    param=value

Returns:
    What format is returned
"""
```

**No Args: section** — redundant with Field() descriptions.

## Discovery Tools Special Rules

`workflow_discover` and `registry_discover` expect **full, detailed user requests**:
```python
# ✓ Good: Full context, natural language
query="I need to check GitHub for PRs every hour, analyze changes, and post summaries to Slack"

# ✗ Bad: Abbreviated technical summary
query="check PRs and notify"
```

**Why**: LLM-powered discovery needs complete context to understand intent.

## Common Mistakes

1. **Arbitrary examples** — `"github-pr-analyzer"` looks like a real workflow but isn't
2. **Missing variants** — Multi-type parameters must show ALL types
3. **Business logic in tools** — Always delegate to services
4. **Overly technical examples** — Discovery tools need user-like descriptions
5. **Inconsistent formatting** — Use `{...}` and `[...]` for brevity

## Files

- `discovery_tools.py` — LLM-powered workflow/component discovery (2 tools)
- `execution_tools.py` — Workflow execute/validate/plan/save/analyze-cache + node testing + read_fields (7 tools)
- `registry_tools.py` — Node describe + list with optional filter (2 tools)
- `workflow_tools.py` — Workflow list/describe from library (2 tools)
- `settings_tools.py` — Settings management (4 tools, **DISABLED**)
- `test_tools.py` — Infrastructure verification (3 tools, **DISABLED**)

## Testing

All tools tested in `tests/test_mcp_server/test_tool_registration.py` — ensures FastMCP can load them and schema is valid.
