# Task 55b MCP Output Control - Complete Handoff Document

## Critical Context
You've already implemented Task 55 (output control for interactive vs non-interactive) and Task 55c (trace output fix). This document covers Task 55b - fixing MCP server output interleaving with progress messages.

## The Problem
User reported MCP server startup messages contaminating the clean progress output:
```
workflow-discovery... ✓ 5.3s
Executing workflow (3 nodes):
  get_messages...Starting Slack MCP Server with stdio transport...
Slack MCP Server running on stdio
 ✓ 0.7s
```

These messages should only appear in verbose mode (`-v` flag), not in default mode.

## Root Cause Discovery

### Why the messages appear
1. MCP servers are spawned as subprocesses by the MCP SDK
2. The servers write startup messages directly to stderr
3. The SDK uses `stdio_client()` which accepts an `errlog` parameter (defaults to `sys.stderr`)
4. The SDK internally uses `anyio.open_process`, NOT `subprocess.Popen`

### Critical SDK Code Path
```python
# In MCP SDK's stdio_client (mcp/client/stdio/__init__.py)
async def stdio_client(server: StdioServerParameters, errlog: TextIO = sys.stderr):
    # ...
    process = await anyio.open_process(
        [command, *args],
        env=env,
        stderr=errlog,  # <-- This is where stderr goes
        cwd=cwd,
    )
```

## Failed Approaches (DON'T DO THESE)

### ❌ Attempt 1: Monkey-patching subprocess.Popen
```python
# This DOESN'T work
if not verbose:
    original_popen = subprocess.Popen
    def silent_popen(*args, **kwargs):
        kwargs['stderr'] = subprocess.DEVNULL
        return original_popen(*args, **kwargs)
    subprocess.Popen = silent_popen
```
**Why it failed**: MCP SDK uses `anyio.open_process`, which doesn't directly use `subprocess.Popen`, so the monkey-patch has no effect.

### ❌ Attempt 2: Using io.StringIO()
```python
# This causes "io.UnsupportedOperation: fileno" error
errlog = sys.stderr if verbose else io.StringIO()
async with stdio_client(params, errlog=errlog) as (read, write):
```
**Why it failed**: `io.StringIO()` doesn't have a `fileno()` method. The subprocess system needs a real file descriptor.

## The Working Solution ✅

### Step 1: Pass verbose flag through shared storage
**File**: `src/pflow/cli/main.py` (around line 588 in `_prepare_shared_storage`)
```python
# Add verbose flag for nodes to check
shared_storage["__verbose__"] = verbose
```

### Step 2: Extract verbose flag in MCP node prep
**File**: `src/pflow/nodes/mcp/node.py` (in `prep` method, around line 124)
```python
# Get verbose flag from shared store (defaults to False if not set)
verbose = shared.get("__verbose__", False)

return {"server": server, "tool": tool, "config": config, "arguments": tool_args, "verbose": verbose}
```

### Step 3: Use subprocess.DEVNULL for stderr redirection
**File**: `src/pflow/nodes/mcp/node.py` (in `_exec_async` method, around line 170)
```python
# Determine where to send MCP server stderr output
import subprocess
import sys
# Use subprocess.DEVNULL for non-verbose mode since io.StringIO() doesn't have a fileno
errlog = sys.stderr if verbose else subprocess.DEVNULL

try:
    # Execute with timeout
    async def _run_session() -> dict:
        # Pass errlog to suppress stderr in non-verbose mode
        async with stdio_client(params, errlog=errlog) as (read, write), ClientSession(read, write) as session:
            # ... rest of the code
```

### Step 4: Clean up (minimal)
```python
finally:
    # No cleanup needed for DEVNULL
    pass
```

## Files Modified

1. **`src/pflow/cli/main.py`**
   - Added `shared_storage["__verbose__"] = verbose` in `_prepare_shared_storage()`

2. **`src/pflow/nodes/mcp/node.py`**
   - Extract verbose flag in `prep()` method
   - Pass `errlog` parameter to `stdio_client()` based on verbose flag
   - Use `subprocess.DEVNULL` when not verbose, `sys.stderr` when verbose

3. **`tests/test_nodes/test_mcp/test_mcp_output_control.py`** (new file)
   - Tests for verbose flag propagation
   - Tests for output control logic

## Critical Gotchas 🚨

### 1. Must use real file descriptor
- ✅ `subprocess.DEVNULL` - has fileno()
- ✅ `sys.stderr` - has fileno()
- ❌ `io.StringIO()` - NO fileno(), causes error
- ❌ `io.BytesIO()` - NO fileno(), would also fail

### 2. The errlog parameter is the key
The MCP SDK's `stdio_client()` accepts an `errlog` parameter. This is the ONLY reliable way to control where MCP server stderr goes.

### 3. Verbose flag must be in shared storage
The verbose flag from CLI must be passed through shared storage as `__verbose__` so nodes can access it. Don't try to pass it through node parameters.

### 4. Testing limitations
Unit tests mock the MCP execution, so they won't catch the fileno error. You need to test with actual MCP commands to verify the fix works.

## How to Test

### Test suppression (default mode):
```bash
# Should show clean progress without MCP messages
uv run pflow "use slack to send a message"
```

### Test verbose mode:
```bash
# Should show MCP server startup messages
uv run pflow -v "use slack to send a message"
```

### Test piped mode:
```bash
# Should output only the result, no progress or MCP messages
echo "test" | uv run pflow "count files" | wc -l
```

## Expected Behavior

### Default mode (no -v flag):
```
workflow-discovery... ✓ 5.3s
Executing workflow (3 nodes):
  get_messages... ✓ 0.7s      # Clean! No MCP output
  analyze_questions... ✓ 8.0s
  send_response... ✓ 0.7s
```

### Verbose mode (with -v flag):
```
workflow-discovery... ✓ 5.3s
Executing workflow (3 nodes):
  get_messages...Starting Slack MCP Server with stdio transport...
Slack MCP Server running on stdio
 ✓ 0.7s
```

### Piped/non-interactive mode:
```
# Only the result, no progress or MCP output
```

## Implementation Status
✅ Verbose flag propagation implemented
✅ MCP node output control implemented
✅ Tests created and passing
✅ Verified with actual MCP commands
✅ All 1882 tests pass

## Common Errors and Solutions

### Error: `io.UnsupportedOperation: fileno`
**Cause**: Using `io.StringIO()` or similar in-memory buffer for stderr
**Solution**: Use `subprocess.DEVNULL` instead

### Error: MCP messages still appearing
**Cause**: Verbose flag not being passed correctly
**Solution**: Check that `__verbose__` is in shared storage and MCP node is reading it

### Error: MCP tools fail silently
**Cause**: Suppressing stdout as well as stderr
**Solution**: Only redirect stderr, leave stdout alone (MCP uses it for communication)

## Key Insight
The MCP SDK's architecture requires working with its `stdio_client` function's `errlog` parameter. Trying to intercept at the subprocess level is ineffective because the SDK uses `anyio.open_process` which has its own subprocess management. The solution must work within the SDK's design, not around it.

---
**Remember**: The fix is already implemented and working. This document is for understanding what was done and why, in case you need to debug or extend it.