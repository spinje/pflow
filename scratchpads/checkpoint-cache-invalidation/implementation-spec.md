# Checkpoint Cache Invalidation Implementation Specification

## Overview

Implement a two-part solution to prevent cached error actions from blocking repair attempts:
1. Don't cache nodes that return error actions
2. Validate cached nodes using configuration hashes

## Requirements

### Functional Requirements

1. **R1**: Nodes returning "error" action MUST NOT be cached
2. **R2**: Cached nodes MUST be validated against current configuration
3. **R3**: Modified nodes MUST have their cache invalidated
4. **R4**: Cache invalidation MUST NOT affect unchanged nodes
5. **R5**: Failed nodes MUST be marked differently from successful nodes

### Non-Functional Requirements

1. **NR1**: Solution must be backward compatible with existing checkpoints
2. **NR2**: Hash computation must be deterministic across runs
3. **NR3**: Performance impact must be minimal (<1ms per node)
4. **NR4**: Solution must not break existing tests

## Implementation Details

### File to Modify

**File**: `src/pflow/runtime/instrumented_wrapper.py`

### Required Imports

Add at the top of the file (after existing imports):

```python
import hashlib
import json
```

### Data Structure Changes

#### Current Structure
```python
shared["__execution__"] = {
    "completed_nodes": [],
    "node_actions": {},
    "failed_node": None
}
```

#### New Structure
```python
shared["__execution__"] = {
    "completed_nodes": [],     # Nodes that succeeded (not error)
    "node_actions": {},        # Action returned by node
    "node_hashes": {},         # NEW: Hash of node configuration
    "failed_node": None        # Node that caused workflow to stop
}
```

### Code Changes

#### 1. Checkpoint Initialization (Line ~302)

**Current Code**:
```python
# Initialize checkpoint structure if not present
if "__execution__" not in shared:
    shared["__execution__"] = {
        "completed_nodes": [],
        "node_actions": {},
        "failed_node": None
    }
```

**New Code**:
```python
# Initialize checkpoint structure if not present
if "__execution__" not in shared:
    shared["__execution__"] = {
        "completed_nodes": [],
        "node_actions": {},
        "node_hashes": {},  # NEW: Store configuration hashes
        "failed_node": None
    }
```

#### 2. Cache Validation Logic (Lines ~307-318)

**Current Code**:
```python
# Check if node already completed (resume case)
if self.node_id in shared["__execution__"]["completed_nodes"]:
    cached_action = shared["__execution__"]["node_actions"].get(self.node_id, "default")

    # Call progress callback for cached node (same format as normal execution)
    callback = shared.get("__progress_callback__")
    if callable(callback):
        depth = shared.get("_pflow_depth", 0)
        with contextlib.suppress(Exception):
            callback(self.node_id, "node_start", None, depth)  # Show node name first
            callback(self.node_id, "node_cached", None, depth)  # Complete the line

    logger.debug(f"Node {self.node_id} skipped (already completed), returning cached action: {cached_action}")
    return cached_action
```

**New Code**:
```python
# Check if node already completed (resume case)
if self.node_id in shared["__execution__"]["completed_nodes"]:
    # Validate cache using configuration hash
    node_config = self._compute_node_config()
    current_hash = self._compute_config_hash(node_config)
    cached_hash = shared["__execution__"]["node_hashes"].get(self.node_id)

    if current_hash == cached_hash:
        # Cache is valid - use it
        cached_action = shared["__execution__"]["node_actions"].get(self.node_id, "default")

        # Call progress callback for cached node (same format as normal execution)
        callback = shared.get("__progress_callback__")
        if callable(callback):
            depth = shared.get("_pflow_depth", 0)
            with contextlib.suppress(Exception):
                callback(self.node_id, "node_start", None, depth)  # Show node name first
                callback(self.node_id, "node_cached", None, depth)  # Complete the line

        logger.debug(f"Node {self.node_id} skipped (already completed), returning cached action: {cached_action}")
        return cached_action
    else:
        # Cache is invalid - node configuration changed
        logger.info(f"Node {self.node_id} configuration changed, invalidating cache")
        shared["__execution__"]["completed_nodes"].remove(self.node_id)
        shared["__execution__"]["node_actions"].pop(self.node_id, None)
        shared["__execution__"]["node_hashes"].pop(self.node_id, None)
        # Fall through to re-execution
```

#### 3. Success Recording (Lines ~333-335)

**Current Code**:
```python
# Record successful completion
shared["__execution__"]["completed_nodes"].append(self.node_id)
shared["__execution__"]["node_actions"][self.node_id] = result
```

**New Code**:
```python
# Record completion only for non-error results
if result != "error":
    # Compute and store configuration hash
    node_config = self._compute_node_config()
    node_hash = self._compute_config_hash(node_config)

    shared["__execution__"]["completed_nodes"].append(self.node_id)
    shared["__execution__"]["node_actions"][self.node_id] = result
    shared["__execution__"]["node_hashes"][self.node_id] = node_hash

    logger.debug(f"Node {self.node_id} cached with hash {node_hash[:8]}...")
else:
    # Don't cache error results - they should be retryable
    logger.debug(f"Node {self.node_id} returned error, not caching")
```

#### 4. Add Helper Methods (Add before the `_run` method)

```python
def _compute_node_config(self) -> dict:
    """Compute the configuration dictionary for the node.

    Returns:
        Dictionary containing node type and parameters
    """
    # Get the actual node (might be wrapped multiple times)
    actual_node = self.inner_node
    while hasattr(actual_node, '_inner_node') or hasattr(actual_node, 'inner_node'):
        if hasattr(actual_node, '_inner_node'):
            actual_node = actual_node._inner_node
        else:
            actual_node = actual_node.inner_node

    # Build configuration dictionary
    node_config = {
        "type": actual_node.__class__.__name__,
        "params": {}
    }

    # Include parameters if present
    if hasattr(actual_node, 'params') and actual_node.params:
        # Sort keys for deterministic hashing
        node_config["params"] = dict(sorted(actual_node.params.items()))

    return node_config

def _compute_config_hash(self, config: dict) -> str:
    """Compute a hash of the node configuration.

    Args:
        config: Node configuration dictionary

    Returns:
        Hexadecimal hash string
    """
    # Serialize to JSON with sorted keys for deterministic hashing
    config_json = json.dumps(config, sort_keys=True)
    # Use MD5 for speed (not cryptographic, just change detection)
    return hashlib.md5(config_json.encode()).hexdigest()
```

## Test Scenarios

### Scenario 1: Error Node Not Cached

**Setup**:
```python
# Node returns "error" action
result = "error"
```

**Expected Behavior**:
- Node NOT added to `completed_nodes`
- Node NOT added to `node_hashes`
- On resume, node executes again

### Scenario 2: Configuration Change Detection

**Setup**:
```python
# First run: node with ignore_errors=false
# Repair: changes to ignore_errors=true
```

**Expected Behavior**:
- Hash changes
- Cache invalidated
- Node re-executes with new configuration

### Scenario 3: Unchanged Node Uses Cache

**Setup**:
```python
# Node succeeds, workflow fails later
# Repair fixes different node
```

**Expected Behavior**:
- Hash matches
- Cache used
- Node shows "↻ cached"

### Scenario 4: Backward Compatibility

**Setup**:
```python
# Existing checkpoint without node_hashes
shared["__execution__"] = {
    "completed_nodes": ["step1"],
    "node_actions": {"step1": "default"}
    # No node_hashes field
}
```

**Expected Behavior**:
- No crash on missing `node_hashes`
- Cache invalidated (no hash to compare)
- Node re-executes

## Edge Cases

### E1: Node with No Parameters

```python
node.params = None  # or {}
```
- Should still compute valid hash
- Use empty dict for params in hash

### E2: Complex Parameter Values

```python
node.params = {
    "config": {"nested": {"deep": "value"}},
    "array": [1, 2, 3]
}
```
- JSON serialization handles nested structures
- Sort keys ensures deterministic ordering

### E3: Multiple Wrapper Layers

```python
# InstrumentedNodeWrapper -> NamespacedNodeWrapper -> ActualNode
```
- Helper method traverses to actual node
- Uses innermost node's configuration

### E4: Non-String Actions

```python
result = None  # Some nodes might return None
```
- Check explicitly for "error" string
- Other falsy values still get cached

## Performance Considerations

### Hash Computation
- MD5 is fast enough (~microseconds per hash)
- Only computed twice per node (save and validate)
- Configuration typically small (<1KB)

### Memory Impact
- One additional hash string (32 chars) per cached node
- Negligible for typical workflows (<100 nodes)

### Cache Lookup
- O(1) dictionary operations
- No performance degradation

## Migration Path

### Phase 1: Deploy Code
- Code handles missing `node_hashes` field gracefully
- Old checkpoints treated as invalid cache

### Phase 2: Monitor
- Log when cache invalidation occurs
- Track hash mismatches

### Phase 3: Optimize (Future)
- Consider more sophisticated cache strategies
- Add metrics for cache hit/miss rates

## Success Criteria

1. **Test passes**: `test-repair-scenarios/test3-multi-node.json` succeeds
2. **No regression**: All existing tests still pass
3. **Observable behavior**:
   - Error nodes show re-execution, not "↻ cached"
   - Modified nodes re-execute after repair
4. **Logs confirm**:
   - "Node X returned error, not caching"
   - "Node X configuration changed, invalidating cache"

## Implementation Order

1. Add imports (hashlib, json)
2. Add helper methods (`_compute_node_config`, `_compute_config_hash`)
3. Update checkpoint initialization
4. Modify cache validation logic
5. Update success recording logic
6. Test with problematic workflow
7. Run full test suite

## Risks and Mitigations

### Risk 1: Hash Collision
- **Probability**: Extremely low with MD5 for config detection
- **Impact**: Wrong cache used
- **Mitigation**: Could use SHA256 if paranoid

### Risk 2: Serialization Differences
- **Probability**: Low if using sorted keys
- **Impact**: False cache misses
- **Mitigation**: Consistent JSON serialization

### Risk 3: Breaking Existing Workflows
- **Probability**: Low due to backward compatibility
- **Impact**: Workflows fail to resume
- **Mitigation**: Graceful handling of missing fields

## Acceptance Tests

### Test 1: Shell Error Recovery
```bash
# Workflow with shell command that fails
# Add ignore_errors=true via repair
# Verify node re-executes and succeeds
```

### Test 2: Template Error After Shell Error
```bash
# test3-multi-node.json scenario
# Verify step3 re-executes after repair
# Verify step4 template error gets fixed
# Verify full workflow succeeds
```

### Test 3: Cache Hit Rate
```bash
# Complex workflow with 10+ nodes
# Fail at last node
# Repair and resume
# Verify first 9 nodes show "↻ cached"
# Verify only repaired node re-executes
```

## Documentation Updates

After implementation, update:
1. `progress-log.md` - Record implementation completion
2. Test files - Add test for cache invalidation
3. Comments in code - Explain why error nodes aren't cached

## Final Checklist

- [ ] Imports added
- [ ] Helper methods implemented
- [ ] Checkpoint initialization updated
- [ ] Cache validation logic added
- [ ] Error nodes excluded from cache
- [ ] Hash stored with cached nodes
- [ ] Tests pass
- [ ] Logs show correct behavior
- [ ] Documentation updated