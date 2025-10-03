# Detailed Implementation Plan: Add Execution State to JSON Output

**Date**: 2025-10-02
**Verification**: All code locations verified against actual source
**Estimated Time**: 30-45 minutes
**Risk Level**: LOW (additive only, no breaking changes)

---

## Overview

Add detailed execution state to `--output-format json` to show agents exactly what happened during workflow execution: which nodes completed, failed, were cached, or not executed.

---

## Phase 1: Add Cache Hit Tracking

**File**: `src/pflow/runtime/instrumented_wrapper.py`

### Change 1.1: Initialize cache hits list

**Location**: Line 535 (in `_initialize_execution_state` method)

**Current code** (lines 528-535):
```python
# Initialize checkpoint structure if not present
if "__execution__" not in shared:
    shared["__execution__"] = {
        "completed_nodes": [],
        "node_actions": {},
        "node_hashes": {},  # Store configuration hashes
        "failed_node": None,
    }
```

**Add after line 535**:
```python
# Initialize cache hits tracking for JSON output
if "__cache_hits__" not in shared:
    shared["__cache_hits__"] = []
```

### Change 1.2: Record cache hits

**Location**: Line 594 (in `_handle_cached_execution` method)

**Current code** (lines 594-603):
```python
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

**Add after line 594 (before callback)**:
```python
# Record cache hit for JSON output
if "__cache_hits__" not in shared:
    shared["__cache_hits__"] = []
shared["__cache_hits__"].append(self.node_id)
```

**Reasoning**: This ensures cache hits are tracked in shared store so JSON output can access them later.

---

## Phase 2: Create Helper Function

**File**: `src/pflow/cli/main.py`

### Change 2.1: Add `_build_execution_steps` helper function

**Location**: After line 636 (after `_extract_workflow_node_count` function)

**Insert**:
```python
def _build_execution_steps(
    workflow_ir: dict[str, Any] | None,
    shared_storage: dict[str, Any],
    metrics_summary: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Build detailed execution steps array for JSON output.

    Args:
        workflow_ir: The workflow IR with nodes list
        shared_storage: Shared store after execution
        metrics_summary: Metrics summary from collector

    Returns:
        List of step dictionaries with status, timing, cache info
    """
    if not workflow_ir or "nodes" not in workflow_ir:
        return []

    # Get execution state
    exec_state = shared_storage.get("__execution__", {})
    completed = exec_state.get("completed_nodes", [])
    failed = exec_state.get("failed_node")
    cache_hits = shared_storage.get("__cache_hits__", [])
    modified_nodes = shared_storage.get("__modified_nodes__", [])

    # Get node timings from metrics
    node_timings = {}
    if metrics_summary:
        workflow_metrics = metrics_summary.get("metrics", {}).get("workflow", {})
        node_timings = workflow_metrics.get("node_timings", {})

    # Build steps array
    steps = []
    for node in workflow_ir["nodes"]:
        node_id = node["id"]

        # Determine status
        if node_id == failed:
            status = "failed"
        elif node_id in completed:
            status = "completed"
        else:
            status = "not_executed"

        # Build step dict
        step = {
            "node_id": node_id,
            "status": status,
            "duration_ms": node_timings.get(node_id),
            "cached": node_id in cache_hits,
        }

        # Mark repaired nodes
        if node_id in modified_nodes:
            step["repaired"] = True

        steps.append(step)

    return steps
```

**Reasoning**: This centralizes execution state extraction logic in one reusable function.

---

## Phase 3: Add Execution State to Success Path

**File**: `src/pflow/cli/main.py`

### Change 3.1: Add execution object to success JSON

**Location**: Line 549 (in `_handle_json_output`, after metrics, before trace save)

**Current code** (lines 548-555):
```python
# Also include detailed metrics for compatibility
result["metrics"] = metrics_summary.get("metrics", {})

# Save JSON output to trace if available
if workflow_trace and hasattr(workflow_trace, "set_json_output"):
    workflow_trace.set_json_output(result)

return _serialize_json_result(result, verbose)
```

**Insert between line 549 and 551**:
```python
# Add execution state if workflow IR available
if workflow_ir and shared_storage:
    steps = _build_execution_steps(workflow_ir, shared_storage, metrics_summary)
    if steps:
        # Count nodes by status
        completed_count = sum(1 for s in steps if s["status"] == "completed")
        nodes_total = len(steps)

        result["execution"] = {
            "duration_ms": metrics_summary.get("duration_ms") if metrics_summary else None,
            "nodes_executed": completed_count,
            "nodes_total": nodes_total,
            "steps": steps,
        }

        # Add repaired flag if any nodes were modified
        modified_nodes = shared_storage.get("__modified_nodes__", [])
        if modified_nodes:
            result["repaired"] = True
```

**Reasoning**: Adds execution state to successful workflow runs showing all step details.

---

## Phase 4: Add Execution State to Error Path (Exception-based)

**File**: `src/pflow/cli/main.py`

### Change 4.1: Add execution state to exception errors

**Location**: Line 713 (in `_create_json_error_output`, before return)

**Current code** (lines 712-715):
```python
# Include detailed metrics
result["metrics"] = metrics_summary.get("metrics", {})

return result
```

**Insert between line 713 and 715 (before return)**:
```python
# Add execution state if available
if shared_storage and "__execution__" in shared_storage:
    exec_state = shared_storage["__execution__"]
    completed = exec_state.get("completed_nodes", [])
    failed = exec_state.get("failed_node")
    cache_hits = shared_storage.get("__cache_hits__", [])

    # Get node timings if available
    node_timings = {}
    if metrics_summary:
        workflow_metrics = metrics_summary.get("metrics", {}).get("workflow", {})
        node_timings = workflow_metrics.get("node_timings", {})

    # Build simplified steps for completed/failed nodes only
    # (we don't have workflow_ir here to know all nodes)
    steps = []
    for node_id in completed:
        steps.append({
            "node_id": node_id,
            "status": "completed",
            "duration_ms": node_timings.get(node_id),
            "cached": node_id in cache_hits,
        })

    if failed and failed not in completed:
        steps.append({
            "node_id": failed,
            "status": "failed",
            "duration_ms": node_timings.get(failed),
            "cached": False,
        })

    if steps:
        result["execution"] = {
            "duration_ms": metrics_summary.get("duration_ms") if metrics_summary else None,
            "nodes_executed": len(completed),
            "steps": steps,
        }
```

**Reasoning**: Exception errors (validation, compilation) may not have full workflow_ir, so we build steps from execution state only.

---

## Phase 5: Add Execution State to Error Path (Runtime)

**File**: `src/pflow/cli/main.py`

### Change 5.1: Enhance runtime error JSON

**Location**: Line 1058 (in `_handle_workflow_error`, after metrics update)

**Current code** (lines 1055-1060):
```python
if metrics_collector:
    llm_calls = shared_storage.get("__llm_calls__", [])
    metrics_summary = metrics_collector.get_summary(llm_calls)
    error_output.update(metrics_summary)

_serialize_json_result(error_output, verbose)
```

**Replace line 1058 with**:
```python
if metrics_collector:
    llm_calls = shared_storage.get("__llm_calls__", [])
    metrics_summary = metrics_collector.get_summary(llm_calls)

    # Add top-level metrics fields
    error_output["duration_ms"] = metrics_summary.get("duration_ms")
    error_output["total_cost_usd"] = metrics_summary.get("total_cost_usd")
    error_output["nodes_executed"] = _extract_workflow_node_count(metrics_summary)
    error_output["metrics"] = metrics_summary.get("metrics", {})

    # Add execution state from shared storage
    if shared_storage and "__execution__" in shared_storage:
        exec_state = shared_storage["__execution__"]
        completed = exec_state.get("completed_nodes", [])
        failed = exec_state.get("failed_node")
        cache_hits = shared_storage.get("__cache_hits__", [])

        # Get node timings
        node_timings = {}
        workflow_metrics = metrics_summary.get("metrics", {}).get("workflow", {})
        node_timings = workflow_metrics.get("node_timings", {})

        # Build steps for completed and failed nodes
        steps = []
        for node_id in completed:
            steps.append({
                "node_id": node_id,
                "status": "completed",
                "duration_ms": node_timings.get(node_id),
                "cached": node_id in cache_hits,
            })

        if failed and failed not in completed:
            steps.append({
                "node_id": failed,
                "status": "failed",
                "duration_ms": node_timings.get(failed),
                "cached": False,
            })

        if steps:
            error_output["execution"] = {
                "duration_ms": metrics_summary.get("duration_ms"),
                "nodes_executed": len(completed),
                "steps": steps,
            }

_serialize_json_result(error_output, verbose)
```

**Reasoning**: Runtime errors have rich execution state - show which nodes succeeded before failure.

---

## Expected Output Formats

### Success Case
```json
{
  "success": true,
  "result": {"output": "..."},
  "workflow": {"action": "saved", "name": "my-workflow"},
  "duration_ms": 1500,
  "total_cost_usd": 0.02,
  "nodes_executed": 3,
  "repaired": true,
  "execution": {
    "duration_ms": 1500,
    "nodes_executed": 3,
    "nodes_total": 3,
    "steps": [
      {"node_id": "fetch", "status": "completed", "duration_ms": 200, "cached": true},
      {"node_id": "analyze", "status": "completed", "duration_ms": 800, "cached": false},
      {"node_id": "save", "status": "completed", "duration_ms": 500, "cached": false, "repaired": true}
    ]
  },
  "metrics": { ... }
}
```

### Error Case (Runtime)
```json
{
  "success": false,
  "error": "Workflow execution failed",
  "is_error": true,
  "errors": [
    {
      "node_id": "analyze",
      "category": "template_error",
      "message": "Template ${data.result} not found",
      "available_fields": ["fetch.data", "fetch.status"]
    }
  ],
  "failed_node": "analyze",
  "duration_ms": 1200,
  "total_cost_usd": 0.01,
  "nodes_executed": 1,
  "execution": {
    "duration_ms": 1200,
    "nodes_executed": 1,
    "steps": [
      {"node_id": "fetch", "status": "completed", "duration_ms": 200, "cached": false},
      {"node_id": "analyze", "status": "failed", "duration_ms": 1000, "cached": false}
    ]
  },
  "metrics": { ... }
}
```

### Error Case (Exception)
```json
{
  "success": false,
  "error": {
    "type": "ValidationError",
    "message": "Invalid workflow structure"
  },
  "workflow": {"action": "unsaved"},
  "duration_ms": 50,
  "total_cost_usd": 0.0,
  "nodes_executed": 0,
  "metrics": { ... }
}
```

---

## Testing Strategy

### Manual Tests

1. **Success case**:
```bash
uv run pflow --output-format json examples/test-workflow.json
```

2. **Error case**:
```bash
uv run pflow --output-format json examples/failing-workflow.json
```

3. **Cache case** (run twice):
```bash
uv run pflow --output-format json test.json
uv run pflow --output-format json test.json  # Should show cached
```

4. **Repair case**:
```bash
uv run pflow --output-format json examples/repairable-workflow.json
```

### Verification Checklist

- [ ] Cache hits tracked in `shared["__cache_hits__"]`
- [ ] Success JSON includes `execution` object
- [ ] Error JSON includes `execution` object when shared_storage available
- [ ] `steps` array shows all nodes with correct status
- [ ] `cached` field correctly identifies cached nodes
- [ ] `repaired` field present when modifications made
- [ ] `duration_ms` per node matches metrics
- [ ] Top-level fields unchanged (backward compatibility)

---

## Files Modified Summary

| File | Lines Added | Lines Modified | Reason |
|------|-------------|----------------|--------|
| `instrumented_wrapper.py` | 7 | 0 | Add cache tracking |
| `main.py` | ~110 | 2 | Add execution state extraction |

**Total**: ~117 lines added, 2 lines modified

---

## Backward Compatibility

✅ **No breaking changes**:
- Top-level `duration_ms`, `total_cost_usd`, `nodes_executed` unchanged
- `metrics.workflow.node_timings` unchanged
- New `execution` object is additive
- Old JSON consumers ignore new fields

---

## Rollback Plan

If issues arise:
1. Remove cache tracking from `instrumented_wrapper.py` (revert 7 lines)
2. Remove execution state extraction from `main.py` (revert ~110 lines)
3. System returns to previous behavior

---

## Next Steps After Implementation

1. Run `make test` - Verify no regressions
2. Run `make check` - Verify code quality
3. Manual testing with all 4 scenarios above
4. Update AGENT_INSTRUCTIONS.md with new JSON format
5. Consider adding unit tests for `_build_execution_steps()`
