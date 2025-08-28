# Task 43: MCP Server Support - Critical Handoff Memo

## 🚨 DO NOT START IMPLEMENTING - READ THIS FIRST

This memo contains critical discoveries and fixes that aren't in the spec or other docs. Read everything, then confirm you're ready.

## 🔥 Critical Bugs Already Fixed (Don't Undo These!)

### 1. The Type Preservation Bug (Root Cause Fix)
**File:** `/src/pflow/runtime/node_wrapper.py` (lines 115-138)

The template resolver was converting ALL values to strings, breaking any node expecting numbers/booleans. I fixed this at the root:
- Simple variable refs like `"${limit}"` now preserve the resolved value's type
- Complex templates like `"Limit is ${limit}"` still return strings
- Non-template values preserve original types

**Test this with:** `test-type-preservation.py` - verifies all type preservation scenarios work

### 2. The Retry Bug (Multiple Server Startups)
**File:** `/src/pflow/nodes/mcp/node.py` (line 69)

Originally had `max_retries=5`, causing 5+ MCP server processes to start simultaneously! Now set to `max_retries=1` (one attempt, no retries). Each retry starts a NEW subprocess - this is architectural debt we can't fix easily without connection pooling.

**Why this matters:** Users saw "Starting Slack MCP Server" 5 times and got "unhandled errors in a TaskGroup" exceptions.

### 3. The Registry 'key' vs 'name' Bug
**Files:**
- `/src/pflow/mcp/discovery.py` (line 204) - params use "key" not "name"
- `/src/pflow/mcp/registrar.py` (lines 166, 179) - outputs use "key", added missing "inputs" field
- `/src/pflow/cli/mcp.py` (lines 276, 355, 363) - CLI display uses "key"

The planner crashed with KeyError: 'key' because MCP registry entries had wrong field names. After fixing, you MUST re-sync servers: `pflow mcp sync --all`

### 4. The Logging Parameter Conflict
**File:** `/src/pflow/nodes/mcp/node.py` (lines 103, 127, 340)

Python's logging system reserves "args" in extra dict. Changed to "tool_args", "mcp_server", "mcp_tool" to avoid conflicts.

## 🎭 The Virtual Node Magic

MCP tools are "virtual nodes" - they don't exist as Python files. Here's how it works:

1. **Registry entries** like `mcp-slack-slack_get_channel_history` all point to the same `MCPNode` class
2. **Compiler injects metadata** (lines 290-305 in `/src/pflow/runtime/compiler.py`):
   ```python
   if node_type.startswith("mcp-"):
       params["__mcp_server__"] = parts[1]  # e.g., "slack"
       params["__mcp_tool__"] = "-".join(parts[2:])  # e.g., "get-channel-history"
   ```
3. **MCPNode uses metadata** to know which server/tool to execute

This is why MCPNode MUST remain universal - no server-specific logic allowed!

## 🔄 The MCP Protocol Reality Check

### What MCP Actually Provides:
- **Input schemas:** YES - as JSON Schema in `tool.inputSchema`
- **Output schemas:** NO - all current servers return `null` for `outputSchema`
- **structuredContent:** Protocol supports it, but no servers use it yet

**Test with:** `check-output-schemas.py` - confirms no server provides output schemas

### What This Means:
- We default to `result: Any` for all MCP tool outputs
- The planner can't reason about output structures
- When servers start providing schemas, our code is ready (see registrar.py line 159)

## 🐛 The Slack Channel Test Case

Channel ID `C09C16NAU5B` is a real Slack channel used for testing. The full test flow:

1. **Direct test:** `test-slack-channel.py` - tests MCPNode directly
2. **Workflow test:** `test-saved-slack-workflow.py` - tests via workflow executor
3. **CLI test:** `test-slack-direct.py` - demonstrates the type bug

The Slack server returns JSON in text content blocks (not structuredContent). This works fine with current implementation but shows servers aren't using the newest protocol features.

## ⚠️ Known Issues & Workarounds

### 1. Pipe Hang Bug (Pre-existing)
ALL workflows with `--file` hang when piped. This isn't MCP-specific - it's a CLI bug documented in `MCP_CRITICAL_FIXES_AND_INSIGHTS.md`.

### 2. Planner Timeouts
The planner sometimes times out with MCP tools. Not sure why - might be the metadata generation step. The workflow still saves correctly though.

### 3. Path Resolution for Filesystem Server
Users must specify paths within configured directories. The filesystem server is restricted to dirs specified during `pflow mcp add`. Example:
```bash
pflow mcp add filesystem npx -- -y @modelcontextprotocol/server-filesystem /tmp /Users/andfal/projects
```

### 4. Environment Variable Expansion
The `${VAR}` syntax in MCP configs expands at runtime, not save time. See `_expand_env_vars()` in MCPNode.

## 📁 Critical Files to Understand

### Core Implementation:
- `/src/pflow/nodes/mcp/node.py` - The universal MCPNode (KEEP IT UNIVERSAL!)
- `/src/pflow/mcp/manager.py` - Configuration storage
- `/src/pflow/mcp/discovery.py` - Tool discovery from servers
- `/src/pflow/mcp/registrar.py` - Virtual node registration

### Test Files That Prove It Works:
- `test-mcp-complete.py` - End-to-end test
- `test-slack-channel.py` - Slack-specific test with channel C09C16NAU5B
- `test-direct-mcp.py` - Direct protocol test
- `scratchpads/mcp-integration/test-client.py` - Protocol validation

### Documentation:
- `MCP_CRITICAL_FIXES_AND_INSIGHTS.md` - Contains the 'key' bug fix details
- `.taskmaster/tasks/task_43/starting-context/` - All the planning docs

## 🔮 Future Work (Not MVP)

### structuredContent Support
The `_extract_result()` method needs enhancement to handle structuredContent when servers start providing it. See `structured-content-fix.py` for proposed implementation.

### Connection Pooling
Currently each execution starts a new server subprocess. Future improvement: cache and reuse connections.

### Better Error Extraction
The nested ExceptionGroup errors from async operations are hard to parse. The `exec_fallback()` method tries but could be improved.

## 🎯 Testing Your Implementation

After any changes:

1. **Re-sync servers:** `uv run pflow mcp sync filesystem`
2. **Test direct execution:** `uv run python test-slack-channel.py`
3. **Test type preservation:** `uv run python test-type-preservation.py`
4. **Test workflow:** `uv run python test-saved-slack-workflow.py`
5. **Verify tools listed:** `uv run pflow mcp tools filesystem`

## 🧠 Non-Obvious Insights

1. **The filesystem server runs in /private/tmp not /tmp on macOS** - symlink magic that trips people up
2. **Slack tools expect channel IDs like C09C16NAU5B**, not channel names
3. **The MCP SDK is async-only** but pflow nodes are sync - hence `asyncio.run()` wrapper
4. **"unhandled errors in a TaskGroup"** usually means parameter type mismatch
5. **The compiler already had the pattern** for metadata injection (__registry__), we just followed it

## 🔗 Key Dependencies

- `mcp[cli]` - The official MCP SDK (async-only)
- MCP servers run as subprocesses via stdio (no HTTP/SSE in MVP)
- Virtual nodes have `file_path: "virtual://mcp"` in registry

## Final Notes

The implementation is complete and working. Users can:
- Configure MCP servers: `pflow mcp add`
- Discover tools: `pflow mcp sync`
- Use tools in workflows
- Access any MCP-compatible service

The architecture is solid - virtual nodes + metadata injection + universal MCPNode. Don't break the universality!

---

**TO THE NEXT AGENT:** Please confirm you've read and understood this handoff before beginning any implementation work on Task 43.