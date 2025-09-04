# MCP Output Control Research Findings

## Problem Summary

MCP (Model Context Protocol) servers are spawning subprocesses that output startup messages like "Starting Slack MCP Server..." directly to stderr, which interleaves with pflow's progress messages and contaminates non-interactive output.

## Key Findings

### 1. MCP Node Implementation

**Location**: `/Users/andfal/projects/pflow-fix-output-control-interactive/src/pflow/nodes/mcp/node.py`

**Key subprocess spawning locations**:
- **Line 167**: `async with stdio_client(params) as (read, write), ClientSession(read, write) as session:`
- **Line 163**: `params = StdioServerParameters(command=config["command"], args=config.get("args", []), env=env if env else None)`

### 2. MCP Discovery Implementation

**Location**: `/Users/andfal/projects/pflow-fix-output-control-interactive/src/pflow/mcp/discovery.py`

**Key subprocess spawning locations**:
- **Line 80**: `async with stdio_client(params) as (read, write), ClientSession(read, write) as session:`
- **Line 71**: `params = StdioServerParameters(command=server_config["command"], args=server_config.get("args", []), env=env if env else None)`

### 3. Current Output Control Infrastructure

**Location**: `/Users/andfal/projects/pflow-fix-output-control-interactive/src/pflow/core/output_controller.py`

**Key capabilities**:
- ✅ `OutputController` class already exists
- ✅ `is_interactive()` method for TTY detection
- ✅ `create_progress_callback()` for progress control
- ✅ CLI already has `--verbose` flag (line 1797 in main.py)
- ✅ Output controller is passed to `_prepare_shared_storage()` (line 995 in main.py)

### 4. Shared Store Integration Pattern

**Location**: `/Users/andfal/projects/pflow-fix-output-control-interactive/src/pflow/cli/main.py`

**How output controller is made available**:
- Lines 588-591: `callback = output_controller.create_progress_callback()` → `shared_storage["__progress_callback__"] = callback`

**Current special keys in shared storage**:
- `__llm_calls__` - LLM call metrics
- `__progress_callback__` - Progress callback function
- `__registry__` - Registry reference
- `__is_planner__` - Planner mode flag

### 5. Subprocess Output Control Pattern

**Location**: `/Users/andfal/projects/pflow-fix-output-control-interactive/src/pflow/nodes/shell/shell.py`

**Best practice example**:
- Line 280: `subprocess.run(..., capture_output=True, ...)`
- Lines 288, 295: Captured stdout/stderr stored in results
- No subprocess output leaks to terminal

### 6. Missing Infrastructure

**What's NOT currently available to nodes**:
- ❌ Verbose flag is not passed to nodes through shared store
- ❌ Output controller is not directly accessible to nodes
- ❌ No standard pattern for subprocess output control in nodes

## Current MCP Output Problem

### Root Cause
The MCP SDK's `stdio_client()` function spawns subprocess servers using `StdioServerParameters` but does NOT capture their stderr output. The server startup messages go directly to the terminal.

### Affected Components
1. **MCP Node execution** - Every time an MCP tool is executed
2. **MCP Discovery** - During `pflow mcp sync` operations
3. Both use the same `stdio_client()` pattern without output control

## Solution Approach

### 1. Extend Shared Store Infrastructure

Add output control information to shared storage:

```python
# In _prepare_shared_storage()
if output_controller:
    shared_storage["__output_controller__"] = output_controller
    shared_storage["__verbose__"] = verbose
```

### 2. Modify MCP Node to Respect Output Control

The MCP node can check for verbosity/interactivity:

```python
# In MCPNode.exec() or _exec_async()
def should_show_mcp_output(self, shared: dict) -> bool:
    """Check if MCP server output should be shown."""
    output_controller = shared.get("__output_controller__")
    if output_controller:
        return output_controller.is_interactive()

    # Fallback: check verbose flag
    return shared.get("__verbose__", False)
```

### 3. Override MCP SDK Subprocess Behavior

The challenge is that `stdio_client()` from the MCP SDK doesn't provide output control options. We need to either:

**Option A**: Patch the environment or subprocess creation
**Option B**: Capture and redirect stderr from the subprocess
**Option C**: Create a wrapper that controls the MCP SDK's subprocess spawning

### 4. Pattern for Other Subprocess-Spawning Nodes

This establishes a pattern that other nodes can follow:
1. Check `shared.get("__output_controller__")` or `shared.get("__verbose__")`
2. Use `subprocess.run(..., capture_output=True)` when not in verbose/interactive mode
3. Only show subprocess output when explicitly requested

## Implementation Strategy

### Phase 1: Extend Shared Store (Low Risk)
1. Add `__output_controller__` and `__verbose__` to shared storage
2. Update MCP node to check these flags
3. Add helper method for output control decisions

### Phase 2: Control MCP Subprocess Output (Higher Risk)
1. Research MCP SDK options for output control
2. Implement subprocess stderr capture/redirect
3. Test with various MCP servers (GitHub, Slack, filesystem)

### Phase 3: Establish Pattern (Documentation)
1. Document the pattern for future subprocess-spawning nodes
2. Update existing nodes if needed
3. Add tests for output control behavior

## Recommendations

1. **Start with shared store extension** - Low risk, establishes infrastructure
2. **Focus on MCP node first** - Highest impact, most visible problem
3. **Test extensively with different MCP servers** - Each server may behave differently
4. **Consider adding `--quiet` flag** - Alternative to verbose control
5. **Update documentation** - Make output control pattern clear for future node developers

## Test Scenarios to Cover

1. **Interactive terminal**: MCP output should be visible when `--verbose` is used
2. **Piped output**: MCP output should be suppressed completely
3. **Non-interactive with verbose**: Behavior depends on implementation choice
4. **MCP sync operations**: Should follow same rules as MCP node execution
5. **Multiple MCP servers**: Ensure consistent behavior across different server types

## Files to Modify

1. `src/pflow/cli/main.py` - Add to `_prepare_shared_storage()`
2. `src/pflow/nodes/mcp/node.py` - Add output control logic
3. `src/pflow/mcp/discovery.py` - Add output control for sync operations
4. Tests - Add output control test cases
5. Documentation - Update node development patterns

## Risk Assessment

- **Low Risk**: Extending shared store infrastructure
- **Medium Risk**: Modifying MCP node output behavior
- **High Risk**: Patching or working around MCP SDK subprocess behavior
- **Technical Risk**: MCP servers may behave differently across platforms
