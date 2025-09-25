# Task 68 Cache Invalidation - Research Findings

## Executive Summary

The checkpoint system implemented in Phase 2 has a critical bug: nodes that return "error" action are cached, preventing the repair system from working. This document consolidates research findings from codebase analysis to guide the implementation of the cache invalidation fix.

## 1. Wrapper Chain Architecture

### Wrapper Order (src/pflow/runtime/compiler.py:544-571)
```
ActualNode (base PocketFlow node)
  ↓
TemplateAwareNodeWrapper (optional, only if templates detected)
  ↓
NamespacedNodeWrapper (optional, if enable_namespacing=True, which is default)
  ↓
InstrumentedNodeWrapper (always applied - line 571)
```

### Attribute Names for Inner Node References
| Wrapper | Attribute | File:Line |
|---------|-----------|-----------|
| `InstrumentedNodeWrapper` | `inner_node` | `instrumented_wrapper.py:34` |
| `NamespacedNodeWrapper` | `_inner_node` | `namespaced_wrapper.py:31` |
| `TemplateAwareNodeWrapper` | `inner_node` | `node_wrapper.py:36` |

### Existing Traversal Logic (instrumented_wrapper.py:45-74)
The `_get_node_params()` method already traverses the wrapper chain:
```python
# Check multiple attribute patterns
if hasattr(current, "inner_node"):
    current = current.inner_node
elif hasattr(current, "_inner_node"):  # NamespacedNodeWrapper
    current = current._inner_node
elif hasattr(current, "_wrapped"):     # Future compatibility
    current = current._wrapped
```

**Key Insight**: We can reuse this pattern for `_compute_node_config()`.

## 2. ShellNode Error Behavior

### When ShellNode Returns "error" (src/pflow/nodes/shell/shell.py:393)
1. **Timeout**: Always returns "error" (exit code -1)
2. **Non-zero exit code** without safe patterns or ignore_errors
3. **Command failures**: Exit codes != 0 that aren't auto-handled

### Safe Patterns (Auto-handled as "default")
- `ls` with glob patterns when no matches
- `grep`/`rg` with exit code 1 (no matches found)
- `which`/`command -v`/`type` for existence checks

### Role of ignore_errors Parameter
- **When true**: Always returns "default" regardless of exit code
- **When false** (default): Follows normal error logic
- **Critical for repair**: Repair adds `ignore_errors: true` to fix failures

## 3. Checkpoint System Architecture

### Current Structure (src/pflow/runtime/instrumented_wrapper.py:299-335)
```python
shared["__execution__"] = {
    "completed_nodes": [],     # List of node IDs that completed
    "node_actions": {},        # Map of node_id -> action returned
    "failed_node": None        # Node that caused workflow to stop
}
```

### Problem Location (Line 333-335)
```python
# This caches ALL nodes, including those returning "error"
shared["__execution__"]["completed_nodes"].append(self.node_id)
shared["__execution__"]["node_actions"][self.node_id] = result
```

### Cache Check Location (Line 307-318)
```python
if self.node_id in shared["__execution__"]["completed_nodes"]:
    cached_action = shared["__execution__"]["node_actions"].get(self.node_id, "default")
    return cached_action  # Returns cached "error" without re-executing!
```

## 4. Repair Service Impact

### How Repair Modifies Nodes
The repair service (src/pflow/execution/repair_service.py) generates entirely new workflow JSON through LLM. Common modifications include:

1. **Adding ignore_errors parameter**:
   ```json
   // Before repair:
   {"command": "ls /nonexistent"}

   // After repair:
   {"command": "ls /nonexistent", "ignore_errors": true}
   ```

2. **Template corrections**:
   ```json
   // Before: ${data.username}
   // After: ${data.login}
   ```

### Configuration Hash Impact
Any parameter modification changes the hash:
- Before: `{"command": "ls /path"}` → Hash: "abc123"
- After: `{"command": "ls /path", "ignore_errors": true}` → Hash: "def456"

Without cache invalidation, the node uses cached "error" even with new parameters.

## 5. Test Structure Insights

### No test-repair-scenarios Directory
The `test-repair-scenarios/test3-multi-node.json` referenced in specs doesn't exist. We'll need to create a test scenario.

### Relevant Test Files
1. `tests/test_runtime/test_checkpoint_tracking.py` - Tests checkpoint behavior
2. `tests/test_integration/test_checkpoint_resume.py` - E2E checkpoint tests
3. `tests/test_execution/test_repair_service.py` - Repair service tests

### Test Pattern Using Side Effects
Tests use `SideEffectNode` that writes to files to verify no duplicate executions - a good pattern for validating cache behavior.

## 6. Backward Compatibility Requirements

### Existing Test Fixtures Without node_hashes
Multiple test fixtures have checkpoint data without the `node_hashes` field:
```python
checkpoint_data = {
    "__execution__": {
        "completed_nodes": ["node1", "node2"],
        "node_actions": {"node1": "default", "node2": "default"},
        "failed_node": "node3"
        # No node_hashes field!
    }
}
```

### Required Defensive Coding Pattern
```python
# Safe access pattern for backward compatibility
node_hashes = shared["__execution__"].get("node_hashes", {})
cached_hash = node_hashes.get(self.node_id)
```

### Initialization Pattern
```python
if "__execution__" not in shared:
    # Create new structure with node_hashes
    shared["__execution__"] = {..., "node_hashes": {}}
else:
    # Add node_hashes to existing checkpoint if missing
    if "node_hashes" not in shared["__execution__"]:
        shared["__execution__"]["node_hashes"] = {}
```

## 7. Implementation Strategy

### Core Changes Required

1. **Don't cache error nodes** (Line 333-335):
   ```python
   if result != "error":
       # Only cache successful nodes
       shared["__execution__"]["completed_nodes"].append(self.node_id)
       shared["__execution__"]["node_actions"][self.node_id] = result
       shared["__execution__"]["node_hashes"][self.node_id] = node_hash
   ```

2. **Validate cache with hash** (Line 307-318):
   ```python
   if self.node_id in shared["__execution__"]["completed_nodes"]:
       current_hash = self._compute_config_hash(node_config)
       cached_hash = shared["__execution__"].get("node_hashes", {}).get(self.node_id)

       if current_hash == cached_hash:
           # Use cache
           return cached_action
       else:
           # Invalidate and re-execute
           self._invalidate_cache_entry(self.node_id)
   ```

### Helper Methods Needed

1. **_compute_node_config()**: Extract actual node params by traversing wrappers
2. **_compute_config_hash()**: Generate deterministic MD5 hash of config
3. **Backward compatibility**: Handle missing node_hashes field gracefully

### Test Strategy

Since test-repair-scenarios doesn't exist, we need to:
1. Create a test workflow that fails with shell error
2. Verify repair adds ignore_errors
3. Confirm node re-executes (not cached) after repair
4. Check that unchanged nodes remain cached

## 8. Critical Success Factors

### Observable Behaviors After Fix
1. **Error nodes show re-execution**, not "↻ cached"
2. **Modified nodes re-execute** after repair
3. **Unchanged nodes stay cached**
4. **Logs show**: "Node X configuration changed, invalidating cache"

### What Should NOT Happen
- Infinite repair loops
- Cached error results after repair
- Breaking existing checkpoints
- Re-execution of unchanged nodes

## 9. Risk Mitigation

### Potential Issues
1. **Hash collisions**: Extremely unlikely with MD5 for config detection
2. **Serialization differences**: Mitigated by sorted JSON keys
3. **Breaking existing workflows**: Handled by backward compatibility

### Testing Requirements
1. Unit tests for hash computation
2. Integration test with real shell failure → repair → resume
3. Backward compatibility test with old checkpoint format
4. Full test suite regression check

## Conclusion

The cache invalidation fix is straightforward but critical:
1. Only cache nodes that return non-error actions
2. Validate cached entries with configuration hashes
3. Handle backward compatibility for existing checkpoints

This enables the repair system to work properly by ensuring modified nodes (especially those with added `ignore_errors: true`) actually re-execute with their new configuration instead of returning cached errors.