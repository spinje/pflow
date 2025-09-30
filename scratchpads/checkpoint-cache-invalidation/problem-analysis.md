# Checkpoint Cache Invalidation Problem Analysis

## Executive Summary

The repair system enters an infinite loop when a node returns an "error" action but has no error edge defined. The node gets cached with its error result, and subsequent repair attempts use the cached error, preventing the repair from ever succeeding.

## The Failing Scenario

### Test Case: test3-multi-node.json

```json
{
  "nodes": [
    {
      "id": "step3",
      "type": "shell",
      "params": {
        "command": "cat /tmp/repair-test-step2.json | jq '.step'"
      }
    },
    {
      "id": "step4",
      "type": "shell",
      "params": {
        "command": "echo 'Result: ${step3.stdout.result}'"
      }
    }
  ],
  "edges": [
    {"from": "step3", "to": "step4"}  // Only defines "default" action path
  ]
}
```

### What Actually Happens

1. **step3 executes**: The `jq` command fails with exit code 5 (JSON parse error)
2. **ShellNode returns "error"**: Per `src/pflow/nodes/shell/shell.py:393`:
   ```python
   if exit_code != 0 and not is_safe and not ignore_errors:
       return "error"  # No error edge defined!
   ```

3. **PocketFlow can't route**: The edge only defines `"default"` action, not `"error"`
   ```
   UserWarning: Flow ends: 'error' not found in ['default']
   ```

4. **Checkpoint records completion**: In `src/pflow/runtime/instrumented_wrapper.py:334`:
   ```python
   # This executes REGARDLESS of action returned
   shared["__execution__"]["completed_nodes"].append(self.node_id)
   shared["__execution__"]["node_actions"][self.node_id] = result  # Stores "error"
   ```

5. **Workflow stops**: No error edge means nowhere to go, step4 never executes

6. **Repair attempts fail**: The repair system tries to fix the workflow, but:
   - Might add `ignore_errors: true` to step3
   - Might add an error edge
   - But step3 is cached with "error" action

7. **Infinite loop**: On resume, `instrumented_wrapper.py:307-318`:
   ```python
   if self.node_id in shared["__execution__"]["completed_nodes"]:
       cached_action = shared["__execution__"]["node_actions"].get(self.node_id, "default")
       # Returns cached "error" action without re-executing!
       return cached_action
   ```

## The Fundamental Design Conflict

### Assumption vs Reality

**Design Assumption**: Checkpointing prevents re-execution of successful nodes during repair

**Reality**: We're also checkpointing failed nodes that return error actions

### Why This Is a Problem

1. **Nodes that return "error" are marked as completed**
   - They executed successfully (no exception)
   - They just returned a non-default action

2. **Cached errors can't be fixed**
   - Even if repair adds `ignore_errors: true`
   - Even if repair adds error edges
   - The cached node still returns "error"

3. **No way to break the loop**
   - Cache uses node ID as key
   - No validation that node configuration matches
   - No way to invalidate specific cached entries

## Code Analysis

### Where Caching Happens

**File**: `src/pflow/runtime/instrumented_wrapper.py`

**Lines 333-335** (in try block after successful execution):
```python
# Record successful completion
shared["__execution__"]["completed_nodes"].append(self.node_id)
shared["__execution__"]["node_actions"][self.node_id] = result
```

**Problem**: This caches ALL nodes that complete, including those returning "error"

### Where Cache Is Used

**Lines 307-318** (before execution):
```python
if self.node_id in shared["__execution__"]["completed_nodes"]:
    cached_action = shared["__execution__"]["node_actions"].get(self.node_id, "default")
    # ... show cached indicator ...
    return cached_action  # Uses cached error!
```

**Problem**: No validation that the cached result is still valid

### Shell Node Error Behavior

**File**: `src/pflow/nodes/shell/shell.py`

**Lines 388-393**:
```python
# After checking safe patterns and ignore_errors
logger.warning(f"Command failed with exit code {exit_code}")
return "error"  # Returns error action for non-zero exit codes
```

**Key Insight**: Shell node returns "error" for any non-zero exit code that isn't explicitly safe (grep, ls globs, etc.) or when `ignore_errors: false`

## Why Current Repair Can't Fix This

### Repair System Flow

1. **Workflow fails** at step3 (returns "error", no edge)
2. **Repair service** might generate:
   ```json
   {
     "nodes": [
       {
         "id": "step3",
         "params": {
           "command": "...",
           "ignore_errors": true  // Added by repair
         }
       }
     ]
   }
   ```

3. **Resume with repaired workflow** BUT:
   - step3 is in `completed_nodes`
   - Returns cached "error" action
   - Never executes with new `ignore_errors: true`

4. **Same failure repeats**

## Observable Symptoms

1. **Progress output shows**:
   ```
   step1... ↻ cached
   step2... ↻ cached
   step3... ↻ cached
   ```
   But no step4 or step5 (workflow stops at step3's error)

2. **PocketFlow warning**:
   ```
   UserWarning: Flow ends: 'error' not found in ['default']
   ```

3. **Multiple repair attempts** all show same cached nodes

4. **Repair eventually gives up**: "Runtime repair failed after 3 attempts"

## Root Causes

### 1. Indiscriminate Caching
We cache ALL completed nodes, not distinguishing between:
- Nodes that succeeded (returned "default")
- Nodes that failed (returned "error")
- Nodes that took alternate paths (returned other actions)

### 2. No Cache Invalidation
When repair modifies a node:
- No detection that node configuration changed
- No way to invalidate that specific cache entry
- Cached result used regardless of changes

### 3. Action vs Success Conflation
The system treats "completed execution" as "successful execution":
- A node that returns "error" has completed execution
- But it hasn't succeeded in the workflow sense
- Yet it's cached as if it succeeded

## Impact

This bug makes the repair system ineffective for:
1. **Shell command failures** without error edges
2. **Any node** that returns non-default actions without corresponding edges
3. **Workflows** where repair needs to modify error-producing nodes

## Test Evidence

### Working Case
When template error is in step4 (never cached due to workflow stopping):
```bash
# step4 fails on template resolution
# Repair can fix the template
# Success
```

### Broken Case
When error is in step3 (gets cached):
```bash
# step3 returns "error"
# Gets cached
# Repair can't fix because cached error keeps returning
# Infinite loop
```

## Conclusion

The checkpoint system's core assumption—that completed nodes should be cached—breaks down when nodes return error actions. The lack of cache invalidation when repairs modify nodes creates an unbreakable loop where cached errors prevent the very repairs meant to fix them.

This is not a rare edge case but a fundamental issue affecting any workflow where:
1. A node can return an error action
2. The workflow doesn't define error edges
3. The repair system attempts to fix the node

The solution requires:
1. Not caching nodes that return error actions
2. Validating cached entries against current node configuration
3. Invalidating cache when nodes are modified by repair