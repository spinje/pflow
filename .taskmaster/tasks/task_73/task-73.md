# Task 73: Implement Checkpoint Persistence for External Agent Repair

## Description
Add checkpoint persistence mechanism to enable external agents using `--no-repair` to resume workflow execution from the last successful node, avoiding duplicate execution of nodes with side effects. This addresses a critical correctness issue where external agent repair loops cause duplicate side effects (API calls, notifications, database writes).

## Status
deprecated

## Dependencies
- Task 71: Extend CLI Commands with tools for agentic workflow building - Provides the foundation of agent-friendly CLI commands and the `--no-repair` flag that this feature extends

## Priority
high

## Details
Currently, when agents use `--no-repair` and handle repair externally, every workflow execution starts fresh with `resume_state=None`. This causes all nodes to re-execute on each iteration, which creates serious problems for workflows with side effects:

- GitHub issues/PRs created multiple times
- Duplicate Slack notifications sent
- Duplicate database writes
- Duplicate API calls (costs, state changes)
- Non-idempotent file operations repeated

**The Problem Is Not Performance - It's Correctness**

While internal repair preserves cache by passing `result.shared_after` as `resume_state`, external agents have no way to preserve checkpoint data between CLI invocations. This fundamentally breaks idempotency for agent repair loops.

### Current Behavior (Internal Repair)
```python
# workflow_execution.py - Internal repair loop
result = execute_workflow(...)  # Node 1-4 succeed, Node 5 fails
repaired_ir = repair_workflow(...)
result = execute_workflow(
    resume_state=result.shared_after  # ← Nodes 1-4 cached!
)
```

### Current Behavior (External Agent Repair)
```python
# main.py - External agent repair
result = execute_workflow(
    enable_repair=False,
    resume_state=None  # ← ALWAYS None, all nodes re-execute!
)
```

### What Needs to Be Built

Implement **Option 5: Hybrid --resume Flag** (from analysis in `scratchpads/task-71-agent-experience/checkpoint-persistence-options.md`):

1. **Automatic Checkpoint Saving**
   - Save `shared["__execution__"]` + `shared["__cache_hits__"]` after each execution
   - Location: `~/.pflow/checkpoints/last-execution.json`
   - Only save metadata (safe, no sensitive data)

2. **--resume Flag**
   - New CLI flag to load last checkpoint
   - Usage: `pflow --no-repair --resume workflow.json`
   - Agent controls when to use caching

3. **Checkpoint Validation**
   - Hash-based compatibility checking
   - Only reuse checkpoint if completed nodes haven't changed
   - Warn and invalidate if incompatible

4. **Checkpoint Format**
```json
{
  "workflow_hash": "md5-of-workflow-ir",
  "execution_state": {
    "completed_nodes": ["node1", "node2"],
    "node_actions": {"node1": "default", "node2": "default"},
    "node_hashes": {"node1": "hash1", "node2": "hash2"},
    "failed_node": "node3"
  },
  "cache_hits": [],
  "timestamp": "2025-10-02T10:30:00",
  "workflow_name": "my-workflow"
}
```

### Key Design Decisions

**Why Hybrid --resume Flag (Option 5)?**
- Simple agent UX (just add --resume)
- Minimal code changes
- Agent controls when to use cache
- Automatic invalidation on incompatibility
- Stateless (no session management)

**Why NOT other options?**
- Auto-load checkpoint: Too risky (race conditions, stale cache)
- Explicit JSON I/O: Too complex for agents
- Session-based: Over-engineered for MVP
- No caching: Breaks correctness for side effects

**Security Considerations**
- Only persist `__execution__` metadata (safe)
- Never store full `shared` store (may have secrets)
- Never store `__llm_calls__` (may have prompts/responses)
- Only store node IDs and hashes

**Cache Invalidation Strategy**
```python
def is_checkpoint_compatible(checkpoint, workflow_ir):
    # Only validate completed nodes
    for node_id in checkpoint["completed_nodes"]:
        node_config = get_node_config(workflow_ir, node_id)
        current_hash = compute_hash(node_config)
        cached_hash = checkpoint["node_hashes"].get(node_id)
        if current_hash != cached_hash:
            return False  # Node changed, invalid
    return True
```

### Implementation Components

**1. Checkpoint Manager** (`src/pflow/core/checkpoint_manager.py`)
- `save_checkpoint(execution_state, workflow_ir, workflow_name)`
- `load_checkpoint()` → Returns checkpoint or None
- `validate_checkpoint(checkpoint, workflow_ir)` → Boolean
- `clear_checkpoint()` → Cleanup

**2. CLI Integration** (`src/pflow/cli/main.py`)
- Add `--resume` flag
- Load checkpoint if flag set and compatible
- Save checkpoint after execution (success or failure)
- Display warning if checkpoint invalidated

**3. Checkpoint File Management**
- Location: `~/.pflow/checkpoints/last-execution.json`
- Atomic writes (write to temp, then rename)
- Auto-cleanup on incompatible workflow
- No TTL needed (single "last" checkpoint)

### Edge Cases to Handle

1. **Checkpoint doesn't exist** → Proceed with `resume_state=None`
2. **Checkpoint incompatible** → Warn user, proceed with `resume_state=None`
3. **Checkpoint corrupted** → Warn user, proceed with `resume_state=None`
4. **Multiple workflows** → Only stores "last execution" (limitation documented)
5. **Concurrent executions** → Last write wins (limitation documented)

### Integration Points

**With execution module**:
- `execute_workflow()` already accepts `resume_state` parameter
- Just need to populate it from loaded checkpoint
- No changes to execution logic needed

**With instrumented_wrapper**:
- Already tracks `__execution__` and `__cache_hits__`
- No changes needed, just extract after execution

**With CLI**:
- Add flag to main command
- Save checkpoint in finally block
- Load checkpoint before execution if flag set

### MVP Scope

**In scope**:
- ✅ Single checkpoint (last execution)
- ✅ Basic compatibility validation
- ✅ Explicit --resume flag
- ✅ Metadata-only persistence
- ✅ Auto-invalidation on incompatibility

**Out of scope** (future enhancements):
- ❌ Multiple checkpoints per workflow
- ❌ Named checkpoints
- ❌ Session-based checkpoints
- ❌ Checkpoint expiration (TTL)
- ❌ Concurrent execution support
- ❌ Checkpoint in JSON output (Option 2)
- ❌ --resume-from <file> parameter

### Known Limitations

1. **Single checkpoint** - Only stores last execution
2. **No concurrent support** - Parallel runs overwrite checkpoint
3. **Workflow-agnostic** - Last execution regardless of which workflow
4. **No cleanup** - Checkpoint persists until overwritten

These limitations are acceptable for MVP and can be addressed in future versions if needed.

## Test Strategy

### Unit Tests

**Checkpoint Manager Tests**:
- `test_save_checkpoint()` - Verify checkpoint saved with correct structure
- `test_load_checkpoint()` - Verify checkpoint loaded correctly
- `test_load_nonexistent_checkpoint()` - Returns None gracefully
- `test_validate_compatible_checkpoint()` - Returns True for unchanged nodes
- `test_validate_incompatible_checkpoint()` - Returns False for changed nodes
- `test_corrupted_checkpoint_handling()` - Graceful fallback on JSON errors
- `test_checkpoint_atomic_write()` - Verify temp file → rename pattern

**Hash Validation Tests**:
- `test_node_hash_unchanged()` - Same config = same hash
- `test_node_hash_changed_params()` - Different params = different hash
- `test_node_hash_changed_type()` - Different type = different hash

### Integration Tests

**CLI Integration Tests**:
- `test_resume_flag_loads_checkpoint()` - Verify --resume loads state
- `test_resume_without_checkpoint()` - Graceful when no checkpoint exists
- `test_resume_invalidates_incompatible()` - Warns and proceeds fresh
- `test_checkpoint_saved_on_success()` - Checkpoint saved after success
- `test_checkpoint_saved_on_failure()` - Checkpoint saved after failure
- `test_resume_with_modified_workflow()` - Detects changes, starts fresh

**End-to-End Tests**:
- `test_external_agent_repair_flow()` - Full agent repair cycle with resume
  1. Execute workflow → Fails at node 3
  2. Agent fixes workflow
  3. Execute with --resume → Nodes 1-2 cached, node 3+ execute
- `test_side_effect_deduplication()` - Verify no duplicate side effects
  1. Mock node with side effect counter
  2. Execute → Fail → Resume
  3. Assert side effect only occurred once

**Checkpoint Compatibility Tests**:
- `test_compatible_checkpoint_with_param_change_in_failed_node()` - OK to change failed node
- `test_incompatible_checkpoint_with_param_change_in_completed_node()` - Not OK to change completed node
- `test_compatible_checkpoint_with_added_nodes()` - OK to add nodes after completed ones
- `test_compatible_checkpoint_with_removed_failed_node()` - OK to remove failed node

### Test Data

Create test workflows:
- `simple-workflow.json` - 3 nodes, fails at node 2
- `side-effect-workflow.json` - Nodes with observable side effects
- `expensive-workflow.json` - Nodes with delays to test caching benefit

### Manual Testing Scenarios

1. **Basic resume flow**:
   ```bash
   pflow --no-repair workflow.json  # Fails
   # ... agent fixes ...
   pflow --no-repair --resume workflow.json  # Resumes
   ```

2. **Incompatible checkpoint**:
   ```bash
   pflow --no-repair workflow.json  # Fails at node 3
   # ... agent modifies node 1 ...
   pflow --no-repair --resume workflow.json  # Warns, starts fresh
   ```

3. **Side effect verification**:
   ```bash
   pflow --no-repair side-effect-workflow.json  # Creates issue #1
   pflow --no-repair --resume side-effect-workflow.json  # No duplicate issue
   ```

### Success Criteria

- ✅ All unit tests pass
- ✅ All integration tests pass
- ✅ Manual testing confirms no duplicate side effects
- ✅ Checkpoint invalidation works correctly
- ✅ Performance: Cache hit reduces execution time by >80% for completed nodes
- ✅ Security: No sensitive data in checkpoint files
- ✅ make test and make check pass
