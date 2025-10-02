# MCP Protocol Best Practices

*Essential protocol guidance for implementing pflow's MCP server*

## Tool Design Best Practices

### Tool Count Limits
- **Keep total tools under 40** - Cursor shows warnings beyond this
- **Ideal: Under 20 tools** - Better for smaller models
- **pflow: 5 tools** - Well within optimal range

### Tool Granularity Pattern
```
❌ BAD: Granular tools for every operation
   - read_file_first_line
   - read_file_last_line
   - read_file_lines_10_to_20

✅ GOOD: Single flexible tool
   - read_file(path, head=None, tail=None, offset=None, limit=None)
```

### Tool Descriptions
- **1-2 sentences maximum** - Be concise
- **Focus on purpose, not implementation**
- **Include "Use this when..." guidance**

Example:
```json
{
  "name": "execute_workflow",
  "description": "Execute a pflow workflow. Returns outputs or errors with checkpoint for recovery."
}
```

## Error Handling Best Practices

### Three-Tier Error Model

1. **Transport Errors** - Connection failures, timeouts
2. **Protocol Errors** - Invalid JSON-RPC, missing methods
3. **Application Errors** - Tool execution failures

### Error Response Pattern

Always use `isError: true` flag so LLMs can see errors:

```python
# Good - LLM can see and respond to error
return CallToolResult(
    isError=True,
    content=[TextContent(text="Workflow not found: test-workflow")]
)

# Bad - Error hidden from LLM
raise Exception("Workflow not found")
```

### Error Information Structure

```json
{
  "error": {
    "code": -32602,  // Standard JSON-RPC error codes
    "message": "Invalid params",
    "data": {
      "param": "workflow_name",
      "reason": "Contains invalid characters"
    }
  }
}
```

## Tool Discovery Pattern

MCP clients discover tools via:
1. Client connects to server
2. Client calls `tools/list`
3. Server returns tool definitions with schemas
4. Client can then call tools

**Critical**: Tool descriptions must be clear enough for LLMs to understand purpose without documentation.

## Schema Definition

Use JSON Schema for parameters:

```json
{
  "inputSchema": {
    "type": "object",
    "properties": {
      "workflow_name": {
        "type": "string",
        "description": "Name of workflow to execute"
      },
      "inputs": {
        "type": "object",
        "description": "Input parameters for workflow"
      }
    },
    "required": ["workflow_name"]
  }
}
```

## Performance Considerations

### Token Usage
Each tool adds ~100-500 tokens to every LLM request:
- Tool name: ~5 tokens
- Description: ~20-50 tokens
- Schema: ~50-400 tokens

**Impact**: 40 tools = 4,000-20,000 tokens overhead per request

### Response Size
- **Paginate large results** - Don't return massive JSON
- **Use summaries** - Return counts before full data
- **Progressive disclosure** - Let LLM request more detail

## Security Patterns

### Never Pass Tokens Through
```python
# ❌ WRONG - Security vulnerability
def call_api(token: str, endpoint: str):
    # Token exposed to LLM

# ✅ RIGHT - Token in server config
def call_api(endpoint: str):
    token = os.environ["API_TOKEN"]
    # Token never exposed
```

### Path Validation
Always validate file paths:
- No path traversal (`../`)
- No absolute paths (unless allowed)
- Sandbox to specific directories

## Protocol Versioning

MCP uses date-based versioning:
- Protocol: `2025-06-18` (current)
- Servers: Semantic versioning (1.0.0)

Include version in server initialization:
```python
FastMCP("pflow", version="1.0.0")
```

## Testing MCP Servers

### Mock Client Testing
```python
from mcp.shared.memory import create_client_server_memory_streams

async def test_tool():
    async with create_client_server_memory_streams() as (read, write):
        # Test without real transport
```

### Stdio Testing
```python
# Send JSON-RPC message
request = {
    "jsonrpc": "2.0",
    "method": "tools/list",
    "id": 1
}
```

## Common Anti-Patterns to Avoid

1. **Creating a tool for every function** - Group related operations
2. **Exposing internal state** - Keep tools stateless
3. **Long tool descriptions** - Be concise
4. **Nested tool calls** - Let LLM orchestrate
5. **Synchronous blocking** - Use async patterns
6. **Exposing sensitive data** - Sanitize all outputs

## pflow-Specific Recommendations

For pflow's 5 tools:
1. **browse_components** - Keep descriptions brief, let LLM filter
2. **execute** - Always return checkpoint on failure
3. **list_library** - Consider pagination for large libraries
4. **describe_workflow** - Include both declared and discovered inputs
5. **save_to_library** - Validate names to prevent overwrites

---

*Based on MCP specification v2025-06-18 and production implementations*