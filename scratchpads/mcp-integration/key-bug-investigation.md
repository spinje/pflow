# Investigation Prompt: 'key' Bug in MCP Workflows

## Recent Fixes Applied

### What We Just Fixed
1. **Workflow JSON validation**: Added missing `ir_version` field requirement
   - Workflows must have `"ir_version": "0.1.0"` to be recognized
   - Without it, CLI falls back to planner (causing apparent "hang")

2. **Output population for --file workflows**: Verified it DOES work!
   - Issue was incorrect source expressions (e.g., `${echo1.message}` instead of `${echo1.echo}`)
   - When source expressions are correct, outputs populate properly
   - Example that works:
     ```json
     {
       "ir_version": "0.1.0",
       "nodes": [{"id": "echo1", "type": "echo", "params": {"message": "Hello"}}],
       "edges": [],
       "outputs": {
         "message": {
           "description": "Echo output",
           "type": "string",
           "source": "${echo1.echo}"  // Correct field name!
         }
       }
     }
     ```

3. **Verified MCP execution**: Confirmed MCP nodes ARE executing (not falling back to built-in nodes)
   - Added debug output to prove MCPNode.exec() is called
   - MCP spawns subprocess, built-in nodes don't
   - Different output keys prove different nodes are running

### Known Remaining Issues
1. **Pipe hang bug**: ALL --file workflows hang when piped (not MCP-specific)
   - Affects: `pflow --file any-workflow.json | cat`
   - NOT an MCP issue, pre-existing CLI bug
   - Likely related to subprocess stderr handling

2. **'key' error**: Occurs specifically with MCP in two scenarios (this investigation)

## Problem Statement
There's a KeyError with message 'key' that occurs in two scenarios:
1. When MCP workflows have declared outputs in the IR
2. When the planner tries to use MCP tools (fails during component-browsing phase)

## What We Know

### Working Cases
- MCP workflows WITHOUT outputs work fine:
  ```json
  {
    "ir_version": "0.1.0",
    "nodes": [
      {
        "id": "list-dirs",
        "type": "mcp-filesystem-list_allowed_directories",
        "params": {}
      }
    ],
    "edges": []
  }
  ```
  This executes successfully and returns results.

- Non-MCP workflows WITH outputs work fine:
  ```json
  {
    "ir_version": "0.1.0",
    "nodes": [{"id": "echo1", "type": "echo", "params": {"message": "Hello"}}],
    "edges": [],
    "outputs": {
      "message": {
        "source": "${echo1.echo}"
      }
    }
  }
  ```

### Failing Cases
1. MCP workflow WITH outputs throws 'key' error during execution
2. Planner fails with 'key' error during component-browsing when MCP tools are available

### What's Been Tried
1. Verified output resolution logic works correctly in isolation
2. Confirmed MCP nodes store results correctly in shared store
3. Tested that template resolution works for MCP namespaced values
4. Checked that the compiler wraps flow.run() to populate outputs

## Investigation Steps

### 1. Find the Exact Error Location
The error message is just 'key' which suggests a KeyError. To find it:
```bash
# Look for the debug trace
cat /Users/andfal/.pflow/debug/pflow-trace-20250826-001525.json | jq .

# Search for KeyError handling that might produce 'key' as message
grep -r "except KeyError" src/pflow/
grep -r "str(e)" src/pflow/ | grep -i key
```

### 2. Check Component Browsing
Since the planner fails during component-browsing when MCP is involved:
```python
# In src/pflow/planning/nodes.py or similar
# Look for the component_browsing function
# Check how it handles MCP nodes differently
# Likely issue: accessing a dictionary key that doesn't exist for MCP nodes
```

### 3. Check Registry Interface for MCP
MCP nodes have a different interface structure in the registry:
```python
# Check src/pflow/mcp/registrar.py
# Look at _create_registry_entry() method
# The interface might be missing a required field that other nodes have
# Specifically check 'params', 'outputs', 'actions' fields
```

### 4. Debug the Planner Path
```bash
# Run with more verbose output
uv run pflow --verbose --trace "list files using mcp"

# Check what the planner is trying to access
# Add debug logging to component_browsing phase
```

### 5. Likely Culprits
Based on the pattern, check these areas:
- **Interface metadata**: MCP nodes might have different interface structure
- **Parameter extraction**: The planner might expect params in a different format
- **Registry entry validation**: Some required field might be missing
- **Namespace handling**: Hyphenated node names (mcp-filesystem-*) might cause issues

### 6. Quick Test
Create a minimal test to isolate the issue:
```python
from pflow.registry import Registry
from pflow.planning.nodes import component_browsing  # or wherever it is

registry = Registry()
nodes = registry.load()

# Get an MCP node
mcp_node = nodes.get("mcp-filesystem-list_allowed_directories")
print("MCP node interface:", mcp_node.get("interface"))

# Compare with a working node
echo_node = nodes.get("echo")
print("Echo node interface:", echo_node.get("interface"))

# Look for missing keys
```

### 7. The Smoking Gun
The error happens in component-browsing, which suggests it's trying to access node metadata. The most likely cause is that MCP nodes' registry entries are missing a field that the planner expects, or have it in a different format.

Check specifically:
- Does the interface have all required keys?
- Are params properly formatted as a list?
- Is the 'key' error coming from accessing interface['something']['key']?

## Next Steps
1. Find the exact line throwing the KeyError
2. Compare MCP registry entries with regular node entries
3. Fix the missing/malformed field in MCP registry creation
4. Test both direct execution and planner with MCP tools

The fix is likely a simple addition of a missing field in the MCP registry entry creation, or handling the different structure of MCP nodes in the component browsing phase.