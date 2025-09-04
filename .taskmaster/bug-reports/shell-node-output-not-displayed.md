# Bug Report: Shell Node Output Not Displayed

## Issue Summary
**Date Discovered**: 2025-01-04
**Date Fixed**: 2025-01-04
**Severity**: High
**Component**: CLI Output Handler
**Status**: FIXED ✅

## Problem Description

Shell node commands were executing successfully but their output was not being displayed to users. Instead of seeing the actual command output (e.g., "Hello from workflow"), users only saw the generic message "Workflow executed successfully".

## Root Cause Analysis

### The Architecture Issue

The problem stemmed from a mismatch between how shell nodes store their output and how the CLI retrieves it, complicated by namespace wrapping:

1. **Shell Node Behavior**:
   - The ShellNode class stores its output in `shared["stdout"]`
   - Also stores `shared["stderr"]` and `shared["exit_code"]`

2. **Namespace Wrapping**:
   - When namespace wrapping is enabled (which it is by default to prevent key collisions)
   - The NamespacedNodeWrapper intercepts the shared store access
   - Writes to `shared["stdout"]` are actually stored at `shared["node_id"]["stdout"]`
   - For example: `shared["echo_node"]["stdout"]` for a node with ID "echo_node"

3. **CLI Output Detection**:
   - The CLI's `_handle_workflow_output()` function checks for output in these keys:
     - `["response", "output", "result", "text"]`
   - It was NOT checking for `"stdout"`
   - It was NOT checking inside namespace dictionaries

4. **The Mismatch**:
   - Shell output stored at: `shared["echo_node"]["stdout"]`
   - CLI looking at: `shared["response"]`, `shared["output"]`, etc.
   - Result: No output found, displays "Workflow executed successfully"

## Symptoms

### User-Visible Issues
1. Shell commands appeared to execute (no errors) but output wasn't shown
2. JSON output mode showed empty result: `{"result": {}}`
3. Explicitly requesting stdout key failed: `--output-key stdout` → "not found"

### Test Results Showing the Issue
```bash
# Before fix
$ uv run pflow /tmp/test_simple.json
Workflow executed successfully  # Should show "Hello from workflow"

$ uv run pflow --output-format json /tmp/test_simple.json
{
  "result": {},  # Empty - stdout not found
  ...
}

$ uv run pflow --output-key stdout /tmp/test_simple.json
Workflow executed successfully
cli: Warning - output key 'stdout' not found in shared store
```

## The Fix

### Code Changes

Modified `/src/pflow/cli/main.py` in two functions:

1. **`_handle_text_output()` - Lines 336-352**:
```python
# Added "stdout" to the standard keys to check
for key in ["response", "output", "result", "text", "stdout"]:
    if key in shared_storage:
        return safe_output(shared_storage[key])

# Added check for stdout in namespace dictionaries
for storage_key, value in shared_storage.items():
    if isinstance(value, dict) and "stdout" in value:
        stdout_value = value["stdout"]
        if stdout_value and str(stdout_value).strip():
            return safe_output(stdout_value)
```

2. **`_collect_json_outputs()` - Lines 510-519**:
```python
# Similar fix for JSON output format
if not result:
    for storage_key, value in shared_storage.items():
        if isinstance(value, dict) and "stdout" in value:
            stdout_value = value["stdout"]
            if stdout_value and str(stdout_value).strip():
                result["stdout"] = stdout_value
                break
```

### Why This Fix Works

1. **Direct stdout support**: First checks if `stdout` exists at the top level (for non-namespaced scenarios)
2. **Namespace traversal**: Then iterates through all top-level keys looking for dictionaries
3. **stdout extraction**: When it finds a dict with `stdout`, it extracts and displays that value
4. **Non-empty check**: Only displays stdout if it contains non-empty content

## Test Verification

### After Fix
```bash
# Text output now works
$ uv run pflow /tmp/test_simple.json
Hello from workflow  ✅

# JSON output includes stdout
$ uv run pflow --output-format json /tmp/test_simple.json
{
  "result": {
    "stdout": "Hello from workflow\n"  ✅
  },
  ...
}

# Piped output works correctly
$ echo "test" | uv run pflow /tmp/test_simple.json | cat
Hello from workflow  ✅
```

## Impact Assessment

### Affected Users
- Anyone using shell nodes in their workflows
- Particularly impacts workflows that rely on shell command output for:
  - Data processing pipelines
  - System administration tasks
  - File manipulation operations
  - Integration with command-line tools

### Severity Justification (High)
- Core functionality broken: Users couldn't see command output
- No workaround available: Even explicit `--output-key` didn't work
- Silent failure: Commands ran but output was lost
- Affected a fundamental node type (shell)

## Lessons Learned

1. **Namespace Wrapping Complexity**: The namespace wrapping system, while preventing collisions, adds complexity to output retrieval. The CLI needs to be aware of this architectural pattern.

2. **Output Key Assumptions**: The CLI was making assumptions about which keys nodes use for output. Different node types use different conventions:
   - LLM nodes: typically use `"response"`
   - Shell nodes: use `"stdout"`
   - Other nodes: various keys

3. **Testing Gap**: This issue wasn't caught because:
   - Most tests focused on LLM nodes (which use `"response"`)
   - Shell node tests may have checked execution success but not output display
   - The namespace wrapping layer wasn't fully considered in output tests

4. **Documentation Need**: Node developers need clear documentation about:
   - Standard output key conventions
   - How namespace wrapping affects their output
   - How the CLI discovers and displays output

## Prevention Recommendations

1. **Standardize Output Keys**: Consider establishing a standard output interface for all nodes
2. **Output Discovery Enhancement**: Make the CLI's output discovery more robust - perhaps check all keys for string values
3. **Namespace-Aware Testing**: Add tests that specifically verify output display with namespace wrapping
4. **Node Developer Guidelines**: Document best practices for node output storage

## Related Issues
- Namespace wrapping implementation: `/src/pflow/runtime/namespaced_wrapper.py`
- Shell node implementation: `/src/pflow/nodes/shell/shell.py`
- Output handler implementation: `/src/pflow/cli/main.py`

## References
- Original test report: `/scratchpads/task-55-output-control/test-report.md`
- Progress log: `/.taskmaster/tasks/task_55/implementation/progress-log.md`

---

*Bug fixed on 2025-01-04 by adding stdout key checking and namespace dictionary traversal to the CLI output handler.*