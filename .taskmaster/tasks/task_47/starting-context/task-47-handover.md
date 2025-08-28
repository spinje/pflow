# Task 47: HTTP Transport Support - Critical Handover

**⚠️ IMPORTANT**: Read this entire document before starting implementation. When done, confirm you're ready to begin.

## 🎯 The Real Challenge You're Facing

You're not just adding HTTP transport. You're navigating a fundamental architectural mismatch: **PocketFlow is synchronous, but the MCP SDK is async-only**. The current stdio implementation "solves" this with `asyncio.run()` creating a new event loop for EVERY execution. This is **intentional and correct for MVP**, not a bug to fix.

## 🔍 Critical Discoveries That Change Everything

### 1. PocketFlow Has AsyncNode (But You Can't Use It Yet)

I discovered that PocketFlow already has comprehensive async support:
- `AsyncNode`, `AsyncFlow`, `AsyncBatchNode`, `AsyncParallelBatchNode` all exist in `pocketflow/__init__.py`
- **BUT**: These are explicitly excluded from MVP scope
- The planner cannot generate AsyncFlow workflows
- All current platform nodes are synchronous

**Why this matters**: Don't try to implement connection pooling with the current sync architecture. It won't work. The `asyncio.run()` pattern MUST stay until pflow enables async support.

### 2. Streamable HTTP vs HTTP+SSE

The user corrected me: **Streamable HTTP** (2025-03-26 spec) replaced the deprecated HTTP+SSE (2024-11-05). Key differences:
- Single `/mcp` endpoint instead of separate SSE and POST endpoints
- Can scale to zero (serverless compatible)
- Optional SSE for streaming responses
- Session management via `Mcp-Session-Id` header

See: `/Users/andfal/projects/pflow-feat-mcp-server-support/.taskmaster/tasks/task_47/research/mcp-http-transport-implementation-guide.md`

### 3. The max_retries=1 Bug That Isn't a Bug

```python
# src/pflow/nodes/mcp/node.py line 68-69
super().__init__(max_retries=1, wait=0)
# CRITICAL: Only ONE attempt (max_retries=1) because each retry
# starts a NEW MCP server subprocess
```

This prevents spawning multiple server processes. With HTTP, this becomes even more critical - you don't want multiple HTTP sessions competing.

## 🏗️ What I Built (And Why It Matters)

### Test Infrastructure Philosophy

I restructured the entire MCP test suite based on **"tests that catch real bugs"** not coverage:

- **Deleted**: `test_mcp_basic.py`, `test_compiler_metadata_injection.py` (100% redundant)
- **Fixed**: Atomic write test that was mocking wrong layer, concurrent access test that wasn't concurrent
- **Added**: Security tests for path traversal, command injection
- **Critical**: Tests for `max_retries=1`, structured data extraction, discovery/registration

Key test files:
- `/tests/test_mcp/test_config_management.py` - Atomic writes, security
- `/tests/test_mcp/test_mcp_discovery_critical.py` - Tool discovery/registration
- `/tests/test_mcp/test_mcp_node_critical.py` - Critical behaviors
- `/tests/test_mcp/test_mcp_integration.py` - Real integration through `flow.run()`

### Documentation Created

- `/.taskmaster/tasks/task_47/research/mcp-http-transport-implementation-guide.md` - Complete implementation guide
- `/tests/test_mcp/REDUNDANCY_ANALYSIS.md` - Why tests were deleted
- `/tests/test_mcp/TEST_FIX_PLAN.md` - Critical test fixes applied

## ⚠️ Hidden Gotchas That Will Bite You

### 1. The Compiler Metadata Injection Is Sacred

```python
# src/pflow/runtime/compiler.py lines 272-287
if node_type.startswith("mcp-"):
    params = params.copy()
    parts = node_type.split("-", 2)  # ["mcp", "server", "tool-name"]
    params["__mcp_server__"] = parts[1]
    params["__mcp_tool__"] = "-".join(parts[2:])
```

This is how MCP nodes know which tool to execute. HTTP transport must preserve this exactly.

### 2. The Planner Can't Generate Error Edges

```python
# src/pflow/nodes/mcp/node.py line 200-204
# WORKAROUND: Return "default" instead of "error" because the planner
# doesn't generate error handling edges in workflows. This prevents
# "Flow ends: 'error' not found" crashes.
return "default"
```

Your HTTP implementation must follow this pattern - always return "default" even on errors.

### 3. Registry Entry Structure Is Fragile

MCP nodes MUST have:
- `"inputs": []` (empty list, not missing)
- Outputs use `"key"` not `"name"`
- `"file_path": "virtual://mcp"`

Wrong structure = compilation failures.

## 🛤️ Implementation Path (Don't Deviate)

### Phase 1: Add HTTP While Keeping asyncio.run() [MVP]

```python
class MCPNode(Node):
    def exec(self, prep_res: dict) -> dict:
        transport = prep_res["config"].get("transport", "stdio")

        if transport == "stdio":
            return asyncio.run(self._exec_async_stdio(prep_res))
        elif transport == "http":
            # MUST use asyncio.run() for MVP!
            return asyncio.run(self._exec_async_http(prep_res))
```

You CANNOT do connection pooling properly in Phase 1. Accept it.

### Phase 2: Migrate to AsyncNode [Post-MVP]

Only when pflow enables async support:
```python
class MCPAsyncNode(AsyncNode):
    _connection_pool = {}  # NOW you can pool connections

    async def exec_async(self, shared, **params):
        # Reuse connections across executions
```

## 🔧 Technical Requirements You Can't Skip

### Session Management

```python
# Server returns session ID during init
response.headers["Mcp-Session-Id"] = "550e8400-e29b-41d4-a716..."

# Client MUST include in all subsequent requests
request.headers["Mcp-Session-Id"] = session_id
```

Without this, every request creates a new session = performance disaster.

### Security (Non-Negotiable)

1. **Origin Validation**: Prevent DNS rebinding attacks
2. **Localhost Binding**: Use 127.0.0.1, never 0.0.0.0
3. **Auth Headers**: Support bearer tokens, API keys

### Config Structure

```json
{
  "servers": {
    "github-http": {
      "url": "https://mcp.github.com",
      "transport": "http",
      "auth": {"type": "bearer", "token": "${GITHUB_TOKEN}"}
    }
  }
}
```

The `MCPServerManager` needs updates to validate URL-based configs.

## 📊 Test Coverage Priorities

Focus on these scenarios (quality over quantity):

1. **Session reuse across executions** - Critical for performance
2. **Session expiration handling** - What happens when server terminates session?
3. **Backwards compatibility detection** - Try Streamable HTTP first, fall back to legacy SSE
4. **Security validation** - Origin headers, auth tokens
5. **Error scenarios** - Network failures, timeouts, invalid responses

Don't test implementation details. Test behaviors that prevent production failures.

## 🔗 Critical Code Locations

- **MCPNode**: `/src/pflow/nodes/mcp/node.py` - Where transport selection happens
- **Config Manager**: `/src/pflow/mcp/manager.py` - Needs URL config support
- **Compiler Injection**: `/src/pflow/runtime/compiler.py` lines 272-287 - Don't break this!
- **Test Examples**: `/tests/test_mcp/test_mcp_node_critical.py` - Shows critical behaviors

## 📚 External Resources

1. [MCP Spec - Transports](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports) - Canonical source
2. [Why Streamable HTTP](https://blog.fka.dev/blog/2025-06-06-why-mcp-deprecated-sse-and-go-with-streamable-http/) - Explains the evolution
3. [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) - Check for HTTP client examples

## 🚨 Final Warnings

1. **DO NOT** try to implement connection pooling with the current sync architecture
2. **DO NOT** remove the `asyncio.run()` pattern - it's correct for MVP
3. **DO NOT** change the metadata injection logic in the compiler
4. **DO NOT** return "error" action from nodes - always "default"
5. **DO NOT** forget session ID management - it's required for HTTP

## 💭 Questions You Should Ask Before Starting

1. Should HTTP be a separate node class or integrated into MCPNode?
2. How to handle servers that support both stdio and HTTP?
3. Should we auto-detect transport from config structure?
4. What's the session timeout strategy?
5. How to test without real MCP HTTP servers?

## 🎬 Your First Steps

1. Read the implementation guide in `.taskmaster/tasks/task_47/research/`
2. Study how the current stdio transport works in `MCPNode._exec_async()`
3. Check if MCP Python SDK has HTTP client support yet
4. Understand the session management requirements
5. Plan your test strategy focusing on real bugs

Remember: You're building for MVP constraints. The elegant solution (AsyncNode with connection pooling) comes later. Build the robust solution now.

---

**When you've read and understood everything above, confirm you're ready to begin implementation.**