# MCP Implementation Guidance

*This document consolidates valuable implementation insights from research.*

## Protocol Best Practices

### Tool Design Limits
- **Keep total tools under 40** - Cursor shows warnings beyond this
- **Ideal: Under 20 tools** - Better for smaller models
- **pflow: 13 tools** - Well within optimal range

### Tool Granularity
```
❌ BAD: Many specific tools
   - workflow_execute_file
   - workflow_execute_saved
   - workflow_execute_json

✅ GOOD: Single flexible tool
   - workflow_execute(workflow: str | dict)
```

### Error Handling Pattern

Always use `isError: true` flag so LLMs can see errors:

```python
# ✅ GOOD - LLM can see and respond to error
return CallToolResult(
    isError=True,
    content=[TextContent(text="Workflow not found: test-workflow")]
)

# ❌ BAD - Error hidden from LLM
raise Exception("Workflow not found")
```

### Token Overhead

Each tool adds ~100-500 tokens to every LLM request:
- Tool name: ~5 tokens
- Description: ~20-50 tokens
- Schema: ~50-400 tokens

**Impact**: 13 tools = ~1,300-6,500 tokens overhead (acceptable)

## Architecture Patterns

### Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    User Interfaces                       │
├──────────────────────┬───────────────────────────────────┤
│      CLI            │         MCP Server                 │
│  (for humans)       │     (for AI agents)                │
├──────────────────────┴───────────────────────────────────┤
│                   pflow Core Libraries                   │
│  WorkflowManager    Registry         execute_workflow    │
└──────────────────────────────────────────────────────────┘
```

**Key Decision**: MCP Server is a peer to CLI, not a wrapper.

### Stateless Pattern (CRITICAL)

```python
# ✅ CORRECT - Fresh instances per request
async def execute_tool(name: str, **params):
    manager = WorkflowManager()  # Fresh instance
    registry = Registry()         # Fresh instance
    # ... use and discard

# ❌ WRONG - Shared state
class PflowMCPServer:
    def __init__(self):
        self.manager = WorkflowManager()  # Shared state!
        self.registry = Registry()        # Will go stale!
```

### Output Interface Pattern

```python
# CLI uses
from pflow.execution.cli_output import CliOutput
output = CliOutput()  # Terminal display

# MCP Server uses
from pflow.execution.null_output import NullOutput
output = NullOutput()  # Silent execution
```

## Security Patterns

### Never Pass Tokens Through Parameters

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

```python
def validate_workflow_name(name: str):
    if any(c in name for c in ['/', '\\', '..', '~']):
        raise SecurityError(f"Invalid characters: {name}")
```

### Sensitive Parameter Sanitization

```python
SENSITIVE_KEYS = {'password', 'token', 'key', 'secret', 'auth'}

def sanitize_for_response(data: dict) -> dict:
    """Redact sensitive values before returning"""
    # Implementation that replaces sensitive values with <REDACTED>
```

## Testing Patterns

### Mock Client Testing

```python
from mcp.shared.memory import create_client_server_memory_streams

async def test_tool():
    async with create_client_server_memory_streams() as (read, write):
        # Test without real transport
```

### Integration Testing

Test the full cycle:
1. Discovery (find existing/nodes)
2. Validation (structural checks)
3. Execution (with traces)
4. Error handling (with checkpoints)

## Common Anti-Patterns to Avoid

1. **Creating a tool for every function** - Group related operations
2. **Exposing internal state** - Keep tools stateless
3. **Long tool descriptions** - Be concise (1-2 sentences)
4. **Nested tool calls** - Let LLM orchestrate
5. **Synchronous blocking** - Use asyncio.to_thread()
6. **Exposing sensitive data** - Sanitize all outputs
7. **Trusting workflow names** - Always validate paths

## Performance Considerations

### Measured Timings
| Operation | Time | Notes |
|-----------|------|-------|
| Registry.load() | 10-50ms | In-memory after first load |
| WorkflowManager.list_all() | 5-20ms | File system reads |
| execute_workflow (simple) | 100-500ms | Without LLM nodes |
| execute_workflow (with LLM) | 2-30s | Depends on model |
| asyncio.to_thread overhead | 1-5ms | Negligible |

### Response Size
- **Paginate large results** - Don't return massive JSON
- **Use summaries** - Return counts before full data
- **Progressive disclosure** - Let LLM request more detail

## Protocol Details

### MCP Versioning
- Protocol: `2024-11-05` (current)
- Server: Semantic versioning (0.1.0)

### JSON-RPC Structure
```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "workflow_execute",
    "arguments": {...}
  },
  "id": 1
}
```

## pflow-Specific Implementation Notes

### Discovery Tools
- Use ComponentBrowsingNode and WorkflowDiscoveryNode directly
- These already have LLM integration
- Don't rebuild the intelligence

### Execution Defaults
- Always JSON output (no format parameter)
- Never auto-repair (no repair flag)
- Always save trace (no trace flag)
- Auto-normalize workflows (add ir_version, edges)

### Workflow Resolution Order
1. Check library (`~/.pflow/workflows/`)
2. Check file path
3. Return error with suggestions

### Critical Patterns
1. **Discovery-first**: Always check existing workflows
2. **Test MCP nodes**: Use registry_run to reveal structure
3. **Validate before execute**: Catch errors early
4. **Agent mode built-in**: No flags needed

## Summary

Key implementation guidelines:
- 13 tools is optimal (under 20 limit)
- Stateless design (fresh instances)
- Direct service integration (not CLI wrapping)
- Security validation on all inputs
- Agent-optimized defaults built-in
- Use existing planning nodes for intelligence

This guidance should be referenced during implementation to avoid common pitfalls and follow proven patterns.