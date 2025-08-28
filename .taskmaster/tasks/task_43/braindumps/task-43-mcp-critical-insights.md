# Task 43: MCP Server Support - Critical Implementation Insights

**⚠️ IMPORTANT**: Read this entire document before implementing anything. At the end, confirm you're ready to begin.

## 🔥 Critical Bugs Already Fixed (Don't Undo These!)

### 1. The Retry Bug That Spawned Zombies
**Location**: `src/pflow/nodes/mcp/node.py:69`

The MCPNode MUST have `max_retries=1` (not 0, not 5!). Here's why:
- `max_retries=0` → PocketFlow bug causes `None` to be passed to `post()` → crashes
- `max_retries=5` → Starts 5 separate MCP server processes → race conditions → "unhandled errors in a TaskGroup"
- `max_retries=1` → Exactly one attempt, no zombie processes

Each retry starts a NEW server subprocess because we're not caching connections. This is a fundamental architectural issue that needs proper connection pooling to fix properly.

### 2. Type Preservation in Template Resolver
**Location**: `src/pflow/runtime/node_wrapper.py:115-138`

I fixed this at the ROOT, not in MCPNode. The template resolver was converting EVERYTHING to strings, breaking all nodes expecting numbers/booleans. The fix:
- Simple variable refs like `"${limit}"` → preserve resolved type (number stays number)
- Complex templates like `"Hello ${name}"` → return string
- Non-template values → preserve original type

Without this fix, Slack's `limit` parameter comes through as `"3"` (string) instead of `3` (number), causing cryptic TaskGroup exceptions.

### 3. Registry Structure (The 'key' vs 'name' Bug)
**Locations**:
- `src/pflow/mcp/discovery.py:204`
- `src/pflow/mcp/registrar.py:166,179`
- `src/pflow/cli/mcp.py:276,355,363`

MCP registry entries were using `"name"` but pflow expects `"key"`. This caused planner to crash with KeyError: 'key'. The fix is already applied in three places:
1. Discovery converts MCP schemas using "key"
2. Registrar creates entries with "key" and "inputs: []"
3. CLI display code reads "key" not "name"

## 🎯 Current Implementation State

### What's Working
- ✅ MCP tools can be discovered and registered as virtual nodes
- ✅ Compiler injects `__mcp_server__` and `__mcp_tool__` metadata
- ✅ MCPNode executes tools with async-to-sync wrapper
- ✅ Environment variable expansion for `${VAR}` in configs
- ✅ CLI commands: add, sync, list, remove, tools, info
- ✅ Filesystem and Slack servers tested and working

### What's NOT Implemented
- ❌ `structuredContent` support (servers with output schemas)
- ❌ `isError` flag handling in responses
- ❌ `resource` and `resource_link` content types
- ❌ Connection pooling (each execution starts new server)
- ❌ HTTP/SSE transport (stdio only)

## 🧠 Architectural Insights You Must Know

### 1. The Virtual Node Pattern
MCP tools are "virtual nodes" - multiple registry entries all point to the same `MCPNode` class. The compiler differentiates them by injecting metadata:

```python
# Registry has: mcp-slack-slack_get_users -> MCPNode
# Compiler sees node type, injects:
params["__mcp_server__"] = "slack"
params["__mcp_tool__"] = "slack_get_users"
```

This happens in `compiler.py:290-305`. The pattern follows how WorkflowExecutor gets `__registry__`.

### 2. MCPNode MUST Remain Universal
**DO NOT** add server-specific logic to MCPNode! I was tempted to handle filesystem paths specially, but this breaks the design. MCPNode is a protocol client that works with ANY server. Server-specific behavior belongs in the server implementation, not the client.

### 3. Registry Manipulation is Legit
Despite initial concerns, directly using `Registry.save()` with virtual paths like `"virtual://mcp"` is fine. The registry accepts arbitrary structures - there's no validation. This isn't a hack, it's using the public API as designed.

## 🐛 Gotchas That Will Bite You

### 1. The Pipe Hang Bug (Pre-existing CLI Issue)
`pflow --file workflow.json` hangs when piped. This is NOT an MCP bug, it affects ALL workflows. The planner times out. Document mentions this is a known issue.

### 2. Slack Server User Cache Initialization
Slack server can take 20-30 seconds to initialize its user cache on first start. You'll see "users cache is not ready yet" errors. This is normal, just wait.

### 3. Path Resolution Confusion
When users specify relative paths, the MCP subprocess inherits pflow's CWD. So:
- User runs from `/Users/me/project/`
- Workflow has `"path": "file.txt"`
- MCP resolves to `/Users/me/project/file.txt`
- But filesystem server might be restricted to `/tmp`
- Result: "Access denied" error

This is BY DESIGN. Users must either:
- Use absolute paths
- Configure server with appropriate directories
- Run pflow from allowed directory

### 4. MCP Protocol Limitations
MCP servers don't provide output schemas (confirmed for filesystem, Slack, GitHub). They return `outputSchema: null`. We default to `"result: Any"` which limits planner understanding. This is a protocol limitation, not our bug.

## 🔧 Testing Patterns

### Quick Filesystem Test
```bash
# Add server
uv run pflow mcp add filesystem npx -- -y @modelcontextprotocol/server-filesystem /tmp

# Sync tools
uv run pflow mcp sync filesystem

# Test
uv run pflow "list allowed directories"
```

### Direct MCPNode Test (Bypasses Planner)
```python
from pflow.nodes.mcp.node import MCPNode

node = MCPNode()
node.set_params({
    "__mcp_server__": "filesystem",
    "__mcp_tool__": "list_allowed_directories"
})
shared = {}
prep_res = node.prep(shared)
exec_res = node.exec(prep_res)
node.post(shared, prep_res, exec_res)
print(shared["result"])
```

### Debug Async Issues
Look for "unhandled errors in a TaskGroup" - this usually means:
1. Multiple server processes (check retry count)
2. Type mismatch (string instead of number)
3. Tool name doesn't exist

## 📁 Key Files and Their Roles

### Core Implementation
- `src/pflow/nodes/mcp/node.py` - The universal MCPNode class
- `src/pflow/mcp/manager.py` - Config storage (~/.pflow/mcp-servers.json)
- `src/pflow/mcp/discovery.py` - Tool discovery from servers
- `src/pflow/mcp/registrar.py` - Updates registry with virtual nodes

### CLI Integration
- `src/pflow/cli/mcp.py` - All MCP subcommands
- `src/pflow/cli/main_wrapper.py` - Routes between workflow and MCP commands

### Critical Fixes
- `src/pflow/runtime/compiler.py:290-305` - Metadata injection
- `src/pflow/runtime/node_wrapper.py:115-138` - Type preservation fix

### Debug Scripts (Very Useful!)
- `scratchpads/mcp-integration/test-client.py` - Protocol validation
- `scratchpads/mcp-integration/debug-mcp-node.py` - Direct node testing
- `scratchpads/mcp-integration/MCP_CRITICAL_FIXES_AND_INSIGHTS.md` - Past bug fixes

## 🚨 Outstanding Issues

### 1. StructuredContent Support (Priority: High)
File: `src/pflow/nodes/mcp/node.py:_extract_result()`
Currently only handles `content` blocks, not `structuredContent`. When FastMCP servers with Pydantic models arrive, they'll return typed data we're not extracting. See `scratchpads/mcp-integration/structured-content-fix.py` for proposed implementation.

### 2. Connection Pooling (Priority: Medium)
Each MCPNode execution starts a new server process. This is inefficient and causes the retry bug. Proper fix needs:
- Cache server connections by server name
- Reuse across multiple tool calls
- Handle connection failures gracefully
- Clean up on workflow completion

### 3. Better Error Extraction (Priority: Low)
The `exec_fallback` method tries to extract meaningful errors from ExceptionGroups but it's hacky. MCP errors get wrapped in multiple layers of exceptions.

## 🎬 What Would Break If You're Not Careful

1. **Changing max_retries** → Multiple server processes or None crashes
2. **Adding server-specific logic to MCPNode** → Breaks universality
3. **Not preserving types in template resolver** → All MCP tools expecting numbers/booleans fail
4. **Using "name" instead of "key" in registry** → Planner can't browse MCP tools
5. **Not syncing after fixes** → Registry has old structure

## 💡 Patterns to Reuse

### Virtual Node Registration
```python
# In registrar.py - multiple entries, same class
nodes["mcp-server-tool1"] = {"class_name": "MCPNode", ...}
nodes["mcp-server-tool2"] = {"class_name": "MCPNode", ...}
```

### Async-to-Sync Wrapper
```python
def exec(self, prep_res):
    return asyncio.run(self._exec_async(prep_res))

async def _exec_async(self, prep_res):
    # Async MCP SDK calls here
```

### Type-Preserving Template Resolution
```python
# Check if simple variable reference
if re.match(r'^\$\{([^}]+)\}$', template):
    # Preserve type
else:
    # Convert to string
```

## 🔗 Essential Documentation

- **MCP Protocol Spec**: https://modelcontextprotocol.io/docs/concepts/tools
- **pflow Registry Pattern**: `src/pflow/registry/registry.py`
- **PocketFlow Node Lifecycle**: `pocketflow/__init__.py`
- **Template Resolution**: `src/pflow/runtime/template_resolver.py`

## ⚡ Quick Wins If You Have Time

1. Add more parameter names to type conversion list (line 115 in node_wrapper.py)
2. Improve error messages when server not configured
3. Add `pflow mcp test <server>` command to validate connections
4. Cache discovered tools to speed up sync

## 🎯 The One Thing You Must Remember

**The MCP integration works but is fragile around retries and types.** Don't change retry behavior without understanding the PocketFlow bug. Don't remove type preservation without testing numeric parameters. The system looks more complex than it is - it's just virtual nodes + metadata injection + async wrapper.

---

**🛑 STOP**: Confirm you've read this entire document and understand the critical fixes before implementing anything. The bugs described here were hard to find and easy to reintroduce.