# MCP Integration: Critical Fixes and Insights Report

## Overview
This document contains ALL critical information discovered and fixed after investigating MCP integration issues. Your memory will be reset to before these discoveries, so this is your complete reference.

## Summary of Critical Fixes Applied

1. **Registry 'key' Bug** - Fixed params/outputs using wrong field name ('name' → 'key')
2. **MCP Retry Bug** - Fixed multiple server processes starting (max_retries: 5 → 1)
3. **Type Preservation Bug** - Fixed template resolver destroying types (affects ALL nodes)
4. **CLI Display Bug** - Fixed CLI trying to access 'name' instead of 'key' in params

## Quick Diagnostic Guide

| Symptom | Likely Cause | Solution |
|---------|--------------|----------|
| KeyError: 'key' | Registry structure wrong | Re-sync MCP servers |
| "unhandled errors in a TaskGroup" | Type mismatch or retry bug | Check param types, ensure max_retries=1 |
| Multiple "Starting MCP Server" messages | Retry bug | Update to max_retries=1 |
| String "3" instead of number 3 | Template resolver bug | Apply type preservation fix |
| Path access denied | User configuration | Check allowed directories in config |
| Generic `result: Any` outputs | Protocol limitation | Wait for servers to provide schemas |

## CRITICAL FIX #1: The 'key' Bug in MCP Registry Entries

### Problem Discovered
- **Symptom**: KeyError with message 'key' when planner tried to use MCP tools
- **Location**: Occurred during `component-browsing` phase in the planner
- **Root Cause**: MCP registry entries had incompatible structure compared to regular nodes

### What Was Wrong
MCP nodes were missing critical fields and using wrong field names:
1. **Missing `inputs` field** - MCP nodes had no `inputs: []` in their interface
2. **Wrong param field names** - Used `"name"` instead of `"key"` in params
3. **Wrong output field names** - Used `"name"` instead of `"key"` in outputs

### The Fix (ALREADY APPLIED)
Two files were modified to fix this:

#### File 1: `src/pflow/mcp/discovery.py` (Line ~204)
Changed from:
```python
param = {
    "name": prop_name,  # WRONG
    "type": self._json_type_to_python(prop_schema.get("type", "str")),
    "required": prop_name in required
}
```
To:
```python
param = {
    "key": prop_name,  # CORRECT - matches pflow convention
    "type": self._json_type_to_python(prop_schema.get("type", "str")),
    "required": prop_name in required
}
```

#### File 2: `src/pflow/mcp/registrar.py`
Two changes:
1. Added missing `inputs` field (Line ~179):
```python
"interface": {
    "description": tool.get("description", f"MCP tool from {server_name}"),
    "inputs": [],  # MCP tools don't read from shared store, only from params
    "params": params,
    "outputs": outputs,
    # ...
}
```

2. Fixed output field name (Line ~166):
```python
outputs = [
    {
        "key": "result",  # Changed from "name" to "key"
        "type": "Any",
        "description": "Tool execution result"
    }
]
```

### Verification
After fix, run this to update registry:
```bash
uv run pflow mcp sync filesystem
```

Then test with:
```bash
uv run pflow "list allowed directories"  # Should work without 'key' error
```

## CRITICAL INSIGHT #2: MCPNode MUST Remain Universal

### The Design Principle
**MCPNode is server-agnostic and must NEVER contain server-specific logic!**

### What This Means
- MCPNode is just a protocol client that works with ANY MCP server
- It passes parameters unchanged to the server
- It never modifies or validates parameters based on server type
- One MCPNode class handles ALL MCP servers (filesystem, GitHub, Slack, etc.)

### What NOT To Do (Tempting But Wrong)
DO NOT add logic like this to MCPNode:
```python
# NEVER DO THIS - Breaks universality!
if server == "filesystem" and "path" in tool_args:
    tool_args["path"] = self._resolve_filesystem_path(tool_args["path"])
```

### Current Correct Implementation
The MCPNode has clear comments (Line ~91-98 in `src/pflow/nodes/mcp/node.py`):
```python
# IMPORTANT: MCPNode is universal and server-agnostic!
# It passes parameters directly to ANY MCP server without modification.
# Never add server-specific logic here - this node must work with:
# - filesystem servers (with their path restrictions)
# - GitHub servers (no paths at all)
# - Slack servers (channel IDs instead of paths)
# - Any future MCP server without code changes
```

## CRITICAL INSIGHT #3: Path Resolution Behavior

### The Issue
When users specify relative paths like `"cat_story.txt"`, the filesystem MCP server fails with:
```
"Error: Access denied - path outside allowed directories: /Users/andfal/projects/pflow-feat-mcp-server-support/cat_story.txt not in /private/tmp"
```

### Why This Happens
1. **User runs pflow** from their project directory
2. **Planner generates** `"path": "cat_story.txt"` (relative path)
3. **MCP subprocess inherits** pflow's current working directory
4. **Filesystem server resolves** relative path from CWD: `cat_story.txt` → `/Users/andfal/projects/pflow-feat-mcp-server-support/cat_story.txt`
5. **But server is restricted** to directories specified in config (e.g., `/private/tmp`)
6. **Result**: Access denied error

### The Configuration
The restriction comes from how the user configured the server:
```bash
# This command sets /tmp as the ONLY allowed directory:
pflow mcp add filesystem npx -- -y @modelcontextprotocol/server-filesystem /tmp

# User can allow multiple directories:
pflow mcp add filesystem npx -- -y @modelcontextprotocol/server-filesystem /tmp /Users/andfal/projects
```

The configuration is stored in `~/.pflow/mcp-servers.json` and is ENTIRELY user-controlled.

### Solutions (Without Breaking MCPNode Universality)
1. **User specifies full paths**: `/private/tmp/cat_story.txt` instead of `cat_story.txt`
2. **User configures server with project directory**: Add `/Users/andfal/projects` to allowed dirs
3. **User configures server with current directory**: Use `.` when adding the server
4. **Documentation**: Make it clear that paths must be within configured directories

## CRITICAL INSIGHT #4: How MCP Configuration Works

### Two Separate Systems
1. **`~/.pflow/mcp-servers.json`** - How to start MCP servers (created by pflow CLI from user input)
2. **Registry entries** - What tools each server provides (discovered from MCP servers)

### Configuration Flow
```
1. User: pflow mcp add filesystem npx -- -y @modelcontextprotocol/server-filesystem /tmp
   ↓
2. CLI saves command to ~/.pflow/mcp-servers.json (NO defaults, exact user input)
   ↓
3. User: pflow mcp sync filesystem
   ↓
4. CLI starts MCP server using saved command
   ↓
5. MCP server reports its tools and capabilities
   ↓
6. CLI saves tool info to registry with correct structure
```

### Key Points
- The `/tmp` restriction is NOT a default - it's what the user specified
- Different users will have different restrictions based on their config
- The CLI doesn't modify or add defaults to the configuration
- Everything in mcp-servers.json comes from the user's CLI command

## Test Commands to Verify Everything Works

```bash
# 1. Re-sync to fix registry entries (if not done already)
uv run pflow mcp sync filesystem

# 2. Test direct execution (should work)
uv run pflow --file test-mcp-simple.json --output-key result

# 3. Test planner can browse MCP tools (no more 'key' error)
uv run pflow "list allowed directories"

# 4. Test file writing (will fail if path outside allowed dirs)
uv run pflow "write hello to /private/tmp/test.txt using mcp"  # Should work
uv run pflow "write hello to test.txt using mcp"  # Will fail (outside allowed dirs)
```

## Files Modified Summary

### Fixed Files
1. **`src/pflow/mcp/discovery.py`** - Changed param fields from "name" to "key"
2. **`src/pflow/mcp/registrar.py`** - Added "inputs" field, changed output fields from "name" to "key"

### Files That MUST NOT Be Modified
1. **`src/pflow/nodes/mcp/node.py`** - Must remain server-agnostic! Has correct comments about universality.

### User Configuration File
- **`~/.pflow/mcp-servers.json`** - User can modify this to allow different directories

## CRITICAL FIX #2: The MCP Retry Bug

### Problem Discovered
- **Symptom**: "Starting Slack MCP Server" appears 5+ times, followed by "unhandled errors in a TaskGroup"
- **Root Cause**: Each retry starts a NEW MCP server subprocess, causing resource conflicts

### Why This Happens
When MCPNode had `max_retries=5`:
1. First attempt starts MCP server process #1
2. If it fails, retry starts MCP server process #2 (process #1 still running!)
3. This continues until 5 server processes are running simultaneously
4. Result: Port conflicts, race conditions, TaskGroup errors

### The Fix (ALREADY APPLIED)
Changed `src/pflow/nodes/mcp/node.py` line 70:
```python
# BEFORE: super().__init__(max_retries=5, wait=2.0)
# AFTER:  super().__init__(max_retries=1, wait=0)  # Only 1 attempt total
```

### Future Improvement Needed
The proper solution would be to cache and reuse MCP server connections across retries, but this requires significant refactoring.

## CRITICAL FIX #3: Template Resolver Type Destruction

### Problem Discovered
- **Symptom**: "unhandled errors in a TaskGroup" when using Slack MCP tools
- **Actual Error**: Passing string "3" instead of number 3 to `limit` parameter
- **Root Cause**: Template resolver converted ALL values to strings, even when no template substitution occurred

### What Was Wrong
The template resolver in `node_wrapper.py` was calling `resolve_string()` for everything:
- Input: `"limit": "${message_count}"` with `message_count: 3` (number)
- Output: `"limit": "3"` (string) - WRONG!

### The Fix (ALREADY APPLIED)
Modified `src/pflow/runtime/node_wrapper.py` lines 115-138 to:
1. **Simple variable references** like `"${limit}"` → preserve the resolved value's type
2. **Complex templates** like `"Limit is ${limit}"` → return strings (as expected)
3. **Non-template values** → preserve original types

This fixes the issue for ALL nodes, not just MCP!

## CRITICAL INSIGHT #5: MCP Protocol Capabilities vs Reality

### The Protocol Supports Output Schemas
The MCP specification (2025-06-18) includes:
- `outputSchema` field for declaring expected output types
- `structuredContent` for typed, validated results
- `isError` flag for tool execution failures

### But Current Servers Don't Use Them
Testing reveals:
- **Filesystem server**: 0/14 tools provide output schemas
- **Slack server**: 0/8 tools provide output schemas
- **GitHub server**: 0/X tools provide output schemas

### Why This Matters
1. **Planner sees generic outputs**: All MCP tools return `result: Any`
2. **Can't chain tools effectively**: Planner doesn't know data structures
3. **pflow is ready**: Our implementation checks for outputSchema and would use it
4. **Servers need upgrading**: They should use FastMCP pattern with Pydantic models

### Current Workaround
We default to `result: Any` when no schema provided, which is correct but limiting.

## CRITICAL INSIGHT #6: Structured Content Support

### What We've Prepared For
The MCPNode has placeholders for handling advanced MCP features:
- `structuredContent` - Typed JSON matching outputSchema
- `isError` flag - Distinguish tool errors from protocol errors
- `resource` and `resource_link` content types

### Current Implementation Gap
`_extract_result()` only handles basic `content` blocks, not `structuredContent`. When servers start providing structured outputs, we'll need to update this method.

### The Good News
- Discovery already detects output schemas
- Registry would display them correctly
- Only the extraction method needs updating
- This is a small change when needed

## Remaining Known Issues (NOT Fixed)

1. **Planner timeout** - Sometimes hangs during metadata generation (separate issue, not MCP-specific)
2. **Pipe hang bug** - ALL workflows with --file hang when piped (pre-existing CLI bug)
3. **Path resolution mismatch** - Users must specify paths within allowed directories (this is by design, not a bug)

## Critical Success Indicators

✅ **Registry structure correct**: MCP nodes have `inputs`, params use `key`, outputs use `key`
✅ **No more 'key' errors**: Planner can browse and use MCP tools
✅ **Direct execution works**: MCP tools execute successfully when paths are correct
✅ **MCPNode remains universal**: No server-specific logic in the node
✅ **Single server startup**: Only one MCP server process per execution (no retries)
✅ **Type preservation**: Template resolver preserves number/boolean/object types
✅ **Slack tools work**: No more TaskGroup errors from type mismatches

## Final Notes

- The MCP integration is WORKING after all these fixes
- The 'key' bug is COMPLETELY FIXED
- The retry bug is FIXED (but needs better solution long-term)
- The type preservation bug is FIXED at the root level
- Path issues are configuration/documentation issues, not code bugs
- MCPNode's universal design is preserved and must stay that way

Remember: When users report errors:
1. **"unhandled errors in a TaskGroup"** - Check if it's the retry bug (multiple server startups) or type mismatch
2. **Path access denied** - Check their `~/.pflow/mcp-servers.json` for allowed directories
3. **Generic outputs** - This is expected until MCP servers provide output schemas
4. **NEVER modify MCPNode** to add server-specific logic - that breaks universality!