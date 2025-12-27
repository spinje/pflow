# Batch Error Display Fix

**Date**: 2024-12-27
**Status**: Ready for implementation
**Priority**: High - User experience issue
**Estimated effort**: 1-2 hours

---

## Executive Summary

When batch processing encounters errors in `continue` mode, the CLI output is confusing and unhelpful. Users see vague warnings with no context, and error details are buried in the results array. This document specifies exactly how to fix this.

---

## The Problem

### Current Behavior

When running a batch workflow with `error_handling: "continue"` and some items fail:

```
WARNING: Command failed with exit code 1
WARNING: Command failed with exit code 1

✓ Workflow completed in 0.394s
Nodes executed (2):
  ✓ source (38ms)
  ✓ process (31ms)

Workflow output:

[{'stdout': 'OK\n', 'exit_code': 0}, {'stdout': '', 'exit_code': 1, 'error': 'Command failed with exit code 1'}, {'stdout': 'OK\n', 'exit_code': 0}, ...]
```

### Problems with Current Output

| Issue | Impact |
|-------|--------|
| **Vague warnings** | "WARNING: Command failed with exit code 1" tells you nothing - which item? what error? |
| **No summary** | No "8/10 succeeded, 2 failed" - user must count manually |
| **Errors buried** | Failed items mixed in results array - have to scan to find `'error':` keys |
| **Node shows success** | `✓ process (31ms)` shows green checkmark even though items failed |
| **No error details visible** | Unless agent explicitly outputs `${process.errors}`, details are hidden |

### Why This Matters

1. **User confusion**: "Did it work? What failed? Should I retry?"
2. **Agent burden**: Agents must remember to output `${process.errors}` for visibility
3. **Debugging difficulty**: Can't quickly see which items failed and why
4. **False confidence**: Green checkmark suggests everything succeeded

---

## Proposed Solution

### New Output Format

**For `continue` mode with failures:**

```
WARNING: Command failed with exit code 1
WARNING: Command failed with exit code 1

✓ Workflow completed in 0.394s
Nodes executed (2):
  ✓ source (38ms)
  ⚠ process (31ms) - 8/10 items succeeded, 2 failed

Batch 'process' errors:
  [1] Command failed with exit code 1
  [4] Command failed with exit code 1

Workflow output:
...
```

**For `continue` mode with NO failures:**

```
✓ Workflow completed in 0.394s
Nodes executed (2):
  ✓ source (38ms)
  ✓ process (31ms) - 10/10 items succeeded

Workflow output:
...
```

**For `fail_fast` mode (unchanged, but clearer):**

```
ERROR: Batch 'process' failed at item [2]: Command failed with exit code 1

❌ Workflow execution failed
Nodes executed (2):
  ✓ source (38ms)
  ✗ process (15ms) - failed at item 3 of 10
```

### Design Decisions

1. **Warning icon (⚠) for partial success**: Distinguishes from full success (✓) and failure (✗)
2. **Summary in node line**: "8/10 items succeeded, 2 failed" - immediate visibility
3. **Error details section**: Separate "Batch errors:" section with index and message
4. **Index in brackets**: `[1]` refers to 0-based index in input array
5. **Keep warnings during execution**: Useful for real-time monitoring, but now contextualized

---

## Implementation Details

### Files to Modify

| File | Purpose |
|------|---------|
| `src/pflow/cli/main.py` | CLI output display logic |
| `src/pflow/execution/display_manager.py` | Execution display coordination |
| `src/pflow/runtime/batch_node.py` | Ensure batch metadata is accessible |

### Key Changes

#### 1. Batch Node Must Signal Partial Failure

The batch node already writes to shared store:
```python
shared[self.node_id] = {
    "results": exec_res,
    "count": len(exec_res),
    "success_count": success_count,
    "error_count": len(self._errors),
    "errors": self._errors if self._errors else None,
}
```

This data is available. The CLI just needs to read and display it.

#### 2. Node Execution Display Must Check for Batch Errors

Currently in display logic:
```python
# Simplified current logic
if node_succeeded:
    print(f"  ✓ {node_id} ({duration}ms)")
else:
    print(f"  ✗ {node_id} ({duration}ms)")
```

**New logic needed:**
```python
# Check if this is a batch node with errors
node_output = shared.get(node_id, {})
if isinstance(node_output, dict) and "error_count" in node_output:
    # This is a batch node
    error_count = node_output.get("error_count", 0)
    success_count = node_output.get("success_count", 0)
    total_count = node_output.get("count", 0)

    if error_count > 0:
        print(f"  ⚠ {node_id} ({duration}ms) - {success_count}/{total_count} items succeeded, {error_count} failed")
    else:
        print(f"  ✓ {node_id} ({duration}ms) - {total_count}/{total_count} items succeeded")
else:
    # Regular node
    if node_succeeded:
        print(f"  ✓ {node_id} ({duration}ms)")
    else:
        print(f"  ✗ {node_id} ({duration}ms)")
```

#### 3. Add Batch Errors Section After Node List

After displaying all nodes, check for batch errors:

```python
# After node list display
for node_id in executed_nodes:
    node_output = shared.get(node_id, {})
    if isinstance(node_output, dict) and node_output.get("errors"):
        errors = node_output["errors"]
        print(f"\nBatch '{node_id}' errors:")
        for err in errors:
            index = err.get("index", "?")
            message = err.get("error", "Unknown error")
            print(f"  [{index}] {message}")
```

#### 4. Improve fail_fast Error Message

Current:
```
ERROR: Workflow execution failed: Item 2 failed: Command failed with exit code 1
```

Better:
```
ERROR: Batch 'process' failed at item [2]: Command failed with exit code 1
```

This requires the exception message to include the node_id. In `batch_node.py`:

```python
# In _exec_sequential when fail_fast raises:
raise RuntimeError(f"Batch '{self.node_id}' failed at item [{idx}]: {error['error']}")
```

### Warning Messages During Execution

The current warnings come from the shell node or other inner nodes:
```
WARNING: Command failed with exit code 1
```

These are useful for real-time monitoring. Options:

**Option A: Suppress warnings, show only in summary**
- Cleaner output
- Lose real-time feedback

**Option B: Enhance warnings with context (recommended)**
```
WARNING: Batch 'process' item [1]: Command failed with exit code 1
```

This requires the batch node to intercept/wrap warnings, which is complex.

**Option C: Keep warnings as-is, rely on summary**
- Simplest implementation
- Summary provides clarity

**Recommendation**: Start with Option C (keep warnings, add summary). Enhance warnings later if needed.

---

## Test Cases

### Test 1: Batch with continue mode, some failures

**Input**: 10 items, 2 fail
**Expected output**:
```
✓ Workflow completed in X.XXXs
Nodes executed (2):
  ✓ source (XXms)
  ⚠ process (XXms) - 8/10 items succeeded, 2 failed

Batch 'process' errors:
  [1] Command failed with exit code 1
  [4] Command failed with exit code 1
```

### Test 2: Batch with continue mode, no failures

**Input**: 10 items, 0 fail
**Expected output**:
```
✓ Workflow completed in X.XXXs
Nodes executed (2):
  ✓ source (XXms)
  ✓ process (XXms) - 10/10 items succeeded
```

### Test 3: Batch with fail_fast mode

**Input**: 10 items, item 3 fails
**Expected output**:
```
ERROR: Batch 'process' failed at item [2]: Command failed with exit code 1

❌ Workflow execution failed
Nodes executed (2):
  ✓ source (XXms)
  ✗ process (XXms) - failed at item 3 of 10
```

### Test 4: Non-batch node (unchanged)

**Expected output**:
```
✓ Workflow completed in X.XXXs
Nodes executed (1):
  ✓ regular_node (XXms)
```

### Test 5: Multiple batch nodes with different outcomes

**Input**: Two batch nodes, first succeeds fully, second has failures
**Expected output**:
```
✓ Workflow completed in X.XXXs
Nodes executed (3):
  ✓ source (XXms)
  ✓ batch1 (XXms) - 5/5 items succeeded
  ⚠ batch2 (XXms) - 3/5 items succeeded, 2 failed

Batch 'batch2' errors:
  [0] Error message 1
  [2] Error message 2
```

---

## Implementation Checklist

- [ ] Identify where node execution results are displayed in CLI
- [ ] Add batch detection logic (check for `error_count` in node output)
- [ ] Modify node line display to show batch summary
- [ ] Add batch errors section after node list
- [ ] Update fail_fast error message format
- [ ] Add tests for new display format
- [ ] Test with real batch workflows
- [ ] Verify non-batch nodes are unaffected

---

## Context: How Batch Node Works

### Batch Config in IR
```json
{
  "id": "process",
  "type": "shell",
  "batch": {
    "items": "${source.response}",
    "as": "user",
    "error_handling": "continue"
  },
  "params": {"command": "..."}
}
```

### Batch Output Structure
```python
shared["process"] = {
    "results": [...],      # Array of per-item results
    "count": 10,           # Total items
    "success_count": 8,    # Items without errors
    "error_count": 2,      # Items with errors
    "errors": [            # Error details (or None if no errors)
        {"index": 1, "item": {...}, "error": "...", "exception": None},
        {"index": 4, "item": {...}, "error": "...", "exception": None}
    ]
}
```

### Detection Logic

A node output is a batch result if:
```python
isinstance(node_output, dict) and "error_count" in node_output and "results" in node_output
```

This distinguishes batch nodes from regular nodes that might have similar keys by coincidence.

---

## Additional Fixes: Trace File Display & Warning Messages

### Issue 1: Trace File Location Hidden in Non-TTY Mode

**Finding**: Trace files ARE saved by default (correct behavior), but the "📊 Workflow trace saved:" message is hidden in non-interactive mode.

**Current code** (`src/pflow/cli/main.py:93-105`):
```python
def _echo_trace(ctx: click.Context, message: str) -> None:
    output_controller = _get_output_controller(ctx)
    if output_controller.is_interactive():  # TTY check - HIDES in pipes, Claude Code, CI/CD
        click.echo(message, err=True)
```

**Problem**: Users running pflow from scripts, CI/CD, or AI agents (Claude Code) never see where traces are saved, even though they ARE being created.

**Fix**: Always show trace file location, or at minimum show when there are errors:
```python
def _echo_trace(ctx: click.Context, message: str, force: bool = False) -> None:
    output_controller = _get_output_controller(ctx)
    if force or output_controller.is_interactive():
        click.echo(message, err=True)
```

Then in batch error cases, call `_echo_trace(ctx, message, force=True)`.

**Alternative**: Remove the `is_interactive()` check entirely. The message goes to stderr and is one line - not noisy.

### Issue 2: Vague WARNING Messages During Batch Execution

**Finding**: The "WARNING: Command failed with exit code 1" messages come from the **shell node** (`src/pflow/nodes/shell/shell.py:692`):

```python
logger.warning(
    f"Command failed with exit code {exit_code}",
    extra={"phase": "post", "exit_code": exit_code},
)
```

**Problem**: The shell node doesn't know it's running inside a batch - no item index, no batch context.

**Options to fix**:

| Option | Approach | Complexity | Recommendation |
|--------|----------|------------|----------------|
| A | Suppress warnings, show summary only | Low | ❌ Loses real-time feedback |
| B | Batch node intercepts logger.warning() | High | ❌ Complex, fragile |
| C | Batch node logs its own context before inner node runs | Medium | ✅ Recommended |
| D | Add warning summary after batch completes | Low | ✅ Good complement to C |

**Recommended approach (Option C + D)**:

1. **Before each item**: Batch node logs context
```python
# In _exec_single() before running inner node:
logger.debug(f"Batch '{self.node_id}' processing item [{idx}]")
```

2. **After batch completes with errors**: Log summary
```python
# In post() when there are errors:
if self._errors:
    for err in self._errors:
        logger.warning(
            f"Batch '{self.node_id}' item [{err['index']}] failed: {err['error']}"
        )
```

This adds context without modifying the shell node.

### Suppressing Shell Node Warnings (Optional Enhancement)

The shell node's `logger.warning()` is called during execution, before batch context is available. To fully replace these with batch-aware messages:

**Option 1: Accept duplicate warnings (simplest)**
- Keep shell node warnings as-is
- Add batch summary after completion
- Users see both (slightly noisy but informative)

**Option 2: Suppress shell warnings in batch mode**

Modify batch_node.py to temporarily suppress warnings:
```python
import logging

def _exec_single(self, idx: int, item: Any) -> tuple:
    # Temporarily raise log level to suppress warnings from inner node
    shell_logger = logging.getLogger("pflow.nodes.shell")
    original_level = shell_logger.level
    shell_logger.setLevel(logging.ERROR)  # Suppress WARNING

    try:
        # ... execute inner node ...
    finally:
        shell_logger.setLevel(original_level)  # Restore
```

**Recommendation**: Start with Option 1 (accept both), iterate if users complain about noise.

### Issue 3: Trace File Contains Full Batch Data

**Verified**: Trace files already capture all batch metadata:
```json
{
  "node_id": "process",
  "success": true,
  "outputs": ["batch_metadata", "count", "error_count", "errors", "results", "success_count"]
}
```

The errors array in trace includes:
- `index`: Which item failed (0-based)
- `item`: The full item object that failed
- `error`: Error message

**Action**: Ensure trace file location is shown when batch errors occur, so users know where to find full details.

---

## Updated Proposed Output

With all fixes applied:

```
✓ Workflow completed in 0.394s
Nodes executed (2):
  ✓ source (38ms)
  ⚠ process (31ms) - 8/10 items succeeded, 2 failed

Batch 'process' errors:
  [1] Command failed with exit code 1
  [4] Command failed with exit code 1

Trace: ~/.pflow/debug/workflow-trace-20251227-121041.json

Workflow output:
...
```

**Changes from original proposal**:
1. Added trace file location at the end
2. Removed the real-time WARNING messages (replaced by post-execution summary)

---

## Updated Implementation Checklist

- [ ] Identify where node execution results are displayed in CLI
- [ ] Add batch detection logic (check for `error_count` in node output)
- [ ] Modify node line display to show batch summary
- [ ] Add batch errors section after node list
- [ ] Update fail_fast error message format
- [ ] **NEW**: Fix `_echo_trace()` to show trace location always (or on errors)
- [ ] **NEW**: Add batch-aware warning logging in `batch_node.py`
- [ ] Add tests for new display format
- [ ] Test with real batch workflows
- [ ] Verify non-batch nodes are unaffected

---

## Files to Modify (Updated)

| File | Purpose |
|------|---------|
| `src/pflow/cli/main.py` | CLI output display logic, fix `_echo_trace()` |
| `src/pflow/execution/display_manager.py` | Execution display coordination |
| `src/pflow/runtime/batch_node.py` | Add batch-aware warning logging |

---

## Out of Scope

1. ~~**Modifying trace files** - Already capture all data~~ (verified - they're complete)
2. **Changing batch node core behavior** - Working correctly
3. **Agent instruction updates** - Display fix makes them unnecessary

---

## Success Criteria

1. Users can immediately see batch success/failure summary
2. Failed item indices are visible without digging
3. Error messages are shown without requiring explicit `${process.errors}` output
4. Non-batch workflows are unaffected
5. Both `continue` and `fail_fast` modes have clear output

---

## Example Workflow for Testing

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "source",
      "type": "http",
      "params": {"url": "https://jsonplaceholder.typicode.com/users", "method": "GET"}
    },
    {
      "id": "process",
      "type": "shell",
      "batch": {
        "items": "${source.response}",
        "as": "user",
        "error_handling": "continue"
      },
      "params": {"command": "if [ ${user.id} -eq 2 ] || [ ${user.id} -eq 5 ]; then exit 1; fi; echo OK"}
    }
  ],
  "edges": [{"from": "source", "to": "process"}]
}
```

Save as `/tmp/batch-test.json` and run:
```bash
uv run pflow /tmp/batch-test.json
```
