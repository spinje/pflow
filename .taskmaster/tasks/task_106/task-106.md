# Task 106: Automatic Workflow Iteration Cache

## ID
106

## Title
Automatic Workflow Iteration Cache for Frictionless AI Agent Development

## Description
Implement automatic caching of node execution results during workflow.json iteration, enabling AI agents to rapidly test and fix workflows without re-executing completed nodes. Zero configuration required - caching is automatic for workflow files, invisible to the agent, and prevents both wasted computation and duplicate side effects.

## Status
not started

## Dependencies
- Task 89: Implement Structure-Only Mode and Selective Data Retrieval - Provides ExecutionCache patterns and infrastructure to extend
- Task 72: Implement MCP Server for pflow - The MCP tools need to support the same caching behavior as CLI

## Priority
high

## Context

### The Problem

When AI agents iterate on workflow.json files:

```
Iteration 1: pflow ./workflow.json
  → Node 1: ✓ (5s, $0.02)
  → Node 2: ✓ (3s, $0.01)
  → Node 3: ✗ fails

Agent fixes node 3...

Iteration 2: pflow ./workflow.json
  → Node 1: ✓ (5s, $0.02)  ← WASTED
  → Node 2: ✓ (3s, $0.01)  ← WASTED
  → Node 3: ✓ (4s, $0.02)
```

**Problems:**
1. **Cost**: Re-running LLM nodes costs money
2. **Time**: 8 seconds wasted per iteration
3. **Side effects**: GitHub issues created twice, emails sent twice, etc.
4. **Agent friction**: No way to avoid this without complex checkpoint management

### The Solution

Automatic iteration caching - no flags, no configuration:

```
Iteration 1: pflow ./workflow.json
  → Node 1: ✓ (5s) → cached
  → Node 2: ✓ (3s) → cached
  → Node 3: ✗ fails

Agent fixes node 3...

Iteration 2: pflow ./workflow.json
  → Node 1: ✓ cached (0.01s)
  → Node 2: ✓ cached (0.01s)
  → Node 3: ✓ (4s)
```

## Scope

### In Scope

| Context | Caching |
|---------|---------|
| `pflow ./workflow.json` | ✅ Automatic |
| `pflow /absolute/path/workflow.json` | ✅ Automatic |
| `pflow workflow.json` (relative) | ✅ Automatic |

### Out of Scope

| Context | Caching | Reason |
|---------|---------|--------|
| `pflow my-saved-workflow` | ❌ None | Saved workflows are validated, no iteration needed |
| `pflow "natural language"` | ❌ None | Planner generates new workflow each time |
| `pflow registry run node` | N/A | Task 89 handles this separately |

### Key Principle

**Saved workflows are production artifacts.** They should never be modified by agents. If iteration is needed, agents copy to pwd and work on the file there. This task only caches file-based workflow execution.

## Details

### Cache Architecture

**Location:** `~/.pflow/cache/workflow-iterations/{workflow_path_hash}/`

**Structure:**
```
~/.pflow/cache/workflow-iterations/
  └── a1b2c3d4/                      # hash of absolute workflow path
      ├── metadata.json              # workflow info, timestamps
      ├── node_1.json                # node 1 outputs
      ├── node_2.json                # node 2 outputs
      └── ...
```

**Metadata file:**
```json
{
  "workflow_path": "/Users/dev/project/workflow.json",
  "workflow_hash": "abc123...",
  "created_at": "2026-01-03T12:00:00Z",
  "last_accessed": "2026-01-03T12:05:00Z",
  "nodes": {
    "node_1": {
      "config_hash": "def456...",
      "status": "completed",
      "cached_at": "2026-01-03T12:00:05Z"
    },
    "node_2": {
      "config_hash": "ghi789...",
      "status": "completed",
      "cached_at": "2026-01-03T12:00:08Z"
    },
    "node_3": {
      "config_hash": "jkl012...",
      "status": "failed",
      "error": "Template variable ${undefined} not found"
    }
  }
}
```

**Node output file:**
```json
{
  "node_id": "node_1",
  "node_type": "llm",
  "config_hash": "def456...",
  "outputs": {
    "response": "...",
    "llm_usage": {...}
  },
  "execution_time_ms": 5000,
  "cached_at": "2026-01-03T12:00:05Z"
}
```

### Cache Invalidation

**Automatic invalidation when:**

1. **Node config changed** - hash(node.type + node.params + node.batch) differs
2. **Upstream node invalidated** - if node_1 re-runs, invalidate node_2+
3. **Workflow structure changed** - node added/removed/reordered before this node
4. **TTL expired** - 24 hours (configurable via settings)

**NOT invalidated when:**
- Downstream nodes change (node_3 change doesn't invalidate node_1)
- Node purpose/comments change (cosmetic)
- Workflow metadata changes (inputs, outputs declarations)

### Cache Hit Logic

```python
def should_use_cache(node_id: str, workflow_ir: dict, cache: IterationCache) -> bool:
    """Determine if cached output can be used."""

    # 1. Cache entry exists?
    if not cache.has_node(node_id):
        return False

    # 2. Node config unchanged?
    current_hash = compute_node_hash(workflow_ir, node_id)
    cached_hash = cache.get_node_hash(node_id)
    if current_hash != cached_hash:
        return False

    # 3. All upstream nodes are cache hits?
    for upstream_id in get_upstream_nodes(workflow_ir, node_id):
        if not cache.is_cache_hit(upstream_id):
            return False

    # 4. TTL not expired?
    if cache.is_expired(node_id):
        return False

    return True
```

### Integration Points

**With workflow executor:**
```python
# In workflow_executor.py

def execute_node(node_id, shared, workflow_ir):
    # Check iteration cache first
    if iteration_cache.should_use_cache(node_id, workflow_ir):
        cached = iteration_cache.load_node(node_id)
        shared.update(cached.outputs)
        logger.info(f"Node {node_id}: using cached result")
        return cached.outputs

    # Execute normally
    result = node.run(shared)

    # Cache successful execution
    if result.success:
        iteration_cache.save_node(node_id, result.outputs, workflow_ir)

    return result
```

**With existing ExecutionCache (Task 89):**
- Reuse binary encoding patterns (`_encode_binary`, `_decode_binary`)
- Reuse atomic write patterns (temp file → rename)
- Different storage location (workflow-iterations vs registry-run)
- Different purpose (iteration vs structure-only retrieval)

### Display Behavior

**Cache hit display:**
```
✓ Node 'fetch-data' completed (cached, 12ms)
✓ Node 'process' completed (cached, 8ms)
✓ Node 'format' completed (2.3s)
```

**Cache invalidation display:**
```
ℹ Node 'fetch-data' config changed, re-executing...
✓ Node 'fetch-data' completed (5.2s)
ℹ Node 'process' invalidated (upstream changed)
✓ Node 'process' completed (3.1s)
```

### CLI Commands

**Inspect cache (optional, for debugging):**
```bash
# Show cache status for a workflow
pflow cache status ./workflow.json

Output:
  Workflow: ./workflow.json
  Cache: ~/.pflow/cache/workflow-iterations/a1b2c3d4/

  Nodes:
    ✓ fetch-data   cached (2 min ago)
    ✓ process      cached (2 min ago)
    ✗ format       not cached (failed)
```

**Clear cache (optional):**
```bash
# Clear cache for specific workflow
pflow cache clear ./workflow.json

# Clear all iteration caches
pflow cache clear --all
```

### Settings Integration

```bash
# Configure TTL (default 24 hours)
pflow settings cache ttl 48h

# Disable iteration caching entirely (not recommended)
pflow settings cache iteration-mode off

# Show cache settings
pflow settings cache show
```

### Security Considerations

1. **File permissions**: Cache files created with 600 (user-only read/write)
2. **Sensitive data**: Cached outputs may contain sensitive data - same security model as workflow execution
3. **No cross-user access**: Cache in user's home directory
4. **Atomic writes**: Prevent corruption from concurrent access

### Edge Cases

**1. Concurrent executions of same workflow:**
- Last write wins (same as Task 73 approach)
- Documented limitation for MVP
- Future: file locking or execution IDs

**2. Workflow file moved/renamed:**
- Cache keyed by absolute path → cache miss
- Agent gets fresh execution (correct behavior)

**3. Node IDs changed:**
- Old cache entries become orphaned
- New node IDs get fresh execution
- Cleanup on next full cache clear

**4. Circular dependencies (shouldn't happen):**
- Validation catches this before execution
- Cache logic assumes DAG structure

**5. Batch nodes:**
- Cache entire batch result, not individual items
- If batch config changes, re-run entire batch

### Performance Targets

| Metric | Target |
|--------|--------|
| Cache lookup | < 10ms |
| Cache write | < 50ms |
| Memory overhead | < 1MB per workflow |
| Disk space per node | ~size of outputs |

### Relationship to Other Tasks

**Task 44 (Build caching system):**
- DEPRECATED by this task
- Task 44 was narrower (only `@flow_safe` nodes)
- This task is more comprehensive (all nodes during iteration)

**Task 73 (Checkpoint persistence):**
- DEPRECATED by this task
- Task 73 required `--resume` flag
- This task is automatic (no flags)
- This task is scoped to file-based workflows only

**Task 89 (Structure-only mode):**
- COMPLEMENTARY - different purposes
- Task 89: Creation-time token efficiency + security
- Task 106: Execution-time iteration efficiency
- Can share infrastructure patterns

## Implementation Components

### New Files

**Core:**
- `src/pflow/core/iteration_cache.py` (~200 LOC)
  - `IterationCache` class
  - `compute_node_hash()`, `should_use_cache()`, `save_node()`, `load_node()`

**CLI:**
- `src/pflow/cli/commands/cache.py` (~100 LOC)
  - `pflow cache status`, `pflow cache clear`

### Modified Files

**Execution:**
- `src/pflow/runtime/workflow_executor.py`
  - Check cache before execution
  - Save to cache after success
  - Display cache hit/miss status

**CLI:**
- `src/pflow/cli/main.py`
  - Detect file-based vs saved workflow
  - Initialize iteration cache for file-based

**Settings:**
- `src/pflow/core/settings.py`
  - Add cache TTL and iteration-mode settings

## Test Strategy

### Unit Tests

**IterationCache class:**
- `test_compute_node_hash_deterministic` - Same config = same hash
- `test_compute_node_hash_changes_on_param_change` - Different params = different hash
- `test_should_use_cache_returns_true_when_valid`
- `test_should_use_cache_returns_false_when_config_changed`
- `test_should_use_cache_returns_false_when_upstream_invalidated`
- `test_should_use_cache_returns_false_when_expired`
- `test_save_and_load_node_roundtrip`
- `test_atomic_write_prevents_corruption`
- `test_binary_data_handling`

### Integration Tests

**End-to-end iteration flow:**
- `test_second_run_uses_cache_for_unchanged_nodes`
- `test_modified_node_invalidates_downstream`
- `test_saved_workflow_does_not_use_iteration_cache`
- `test_cache_cleared_on_explicit_clear`

**Side effect prevention:**
- `test_side_effect_node_not_re_executed_on_cache_hit`
  - Mock node with counter
  - Run twice, assert counter = 1

### Performance Tests

- `test_cache_lookup_under_10ms`
- `test_cache_write_under_50ms`
- `test_handles_100_node_workflow`

## Success Criteria

1. ✅ AI agent can iterate on workflow.json without re-running completed nodes
2. ✅ No flags or configuration required - just works
3. ✅ Cache invalidation correctly detects node changes
4. ✅ Side effects not duplicated (cache hit = no re-execution)
5. ✅ Saved workflows unaffected (no caching)
6. ✅ `make test` and `make check` pass
7. ✅ Performance targets met

## Future Enhancements (Out of Scope)

- **Concurrent execution support** - File locking for parallel runs
- **Cache sharing** - Share caches across similar workflows
- **Selective re-run** - `pflow workflow.json --rerun=node_3`
- **Cache export** - Package cache for reproducibility
- **Remote cache** - Cloud-based cache for team workflows
