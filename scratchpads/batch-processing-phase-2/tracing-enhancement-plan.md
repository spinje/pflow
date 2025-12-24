# Batch Processing Tracing Enhancement Plan

## Problem

Batch processing appears as a single node in traces with minimal visibility:
- No per-item timing
- No parallel vs sequential indicator
- No batch size metadata
- No execution mode summary

## Solution: Enhance Batch Output in `post()`

The tracing system already captures `shared[node_id]` in `shared_after`. By enriching what PflowBatchNode writes to its output, we get free tracing integration with zero changes to the tracing infrastructure.

## Key Insight

```python
# InstrumentedNodeWrapper._run() (line 677):
self._record_trace(duration_ms, shared_before, dict(shared), success=trace_success)
#                                              ^^^^^^^^^^^
#                                              This captures shared AFTER post() runs

# PflowBatchNode.post() writes to:
shared[self.node_id] = {...}  # This is in shared_after!
```

**Result**: Any metadata we add to `shared[node_id]` appears in traces automatically.

---

## Implementation

### Step 1: Track Per-Item Timing

**Change return type of `_exec_single()` and `_exec_single_with_node()`**:

```python
# Current:
def _exec_single(self, idx: int, item: Any) -> tuple[dict | None, dict | None]:
    return (result, error_info)

# New:
def _exec_single(self, idx: int, item: Any) -> tuple[dict | None, dict | None, float]:
    return (result, error_info, duration_ms)
```

**Track timing inside each method**:

```python
def _exec_single(self, idx: int, item: Any) -> tuple[dict | None, dict | None, float]:
    import time
    start_time = time.perf_counter()

    # ... existing logic ...

    duration_ms = (time.perf_counter() - start_time) * 1000
    return (result, error_info, duration_ms)
```

### Step 2: Collect Timings in `_exec_sequential()` and `_exec_parallel()`

```python
def _exec_sequential(self, items: list) -> tuple[list, list[float]]:
    results = []
    item_timings = []

    for idx, item in enumerate(items):
        result, error, duration_ms = self._exec_single(idx, item)
        results.append(result)
        item_timings.append(duration_ms)
        # ... error handling ...

    return (results, item_timings)
```

### Step 3: Store Timings as Instance State

```python
def __init__(self, ...):
    # ... existing ...
    self._item_timings: list[float] = []
```

### Step 4: Update `_exec()` to Store Timings

```python
def _exec(self, items: list) -> list:
    self._errors = []
    self._item_timings = []

    if self.parallel:
        results, timings = self._exec_parallel(items)
    else:
        results, timings = self._exec_sequential(items)

    self._item_timings = timings
    return results
```

### Step 5: Enhanced Output in `post()`

```python
def post(self, shared: dict, prep_res: list, exec_res: list) -> str:
    success_count = sum(1 for r in exec_res if r is not None and not self._extract_error(r))

    # Calculate timing statistics
    timings = self._item_timings
    timing_stats = {}
    if timings:
        timing_stats = {
            "total_items_ms": round(sum(timings), 2),
            "avg_item_ms": round(sum(timings) / len(timings), 2),
            "min_item_ms": round(min(timings), 2),
            "max_item_ms": round(max(timings), 2),
        }

    # Write enhanced results
    shared[self.node_id] = {
        # Existing fields (backward compatible)
        "results": exec_res,
        "count": len(exec_res),
        "success_count": success_count,
        "error_count": len(self._errors),
        "errors": self._errors if self._errors else None,

        # NEW: Batch execution metadata
        "batch_metadata": {
            "parallel": self.parallel,
            "max_concurrent": self.max_concurrent if self.parallel else None,
            "max_retries": self.max_retries,
            "retry_wait": self.retry_wait,
            "execution_mode": "parallel" if self.parallel else "sequential",
            "timing": timing_stats,
        },
    }

    return "default"
```

---

## Output Format

### Current (before enhancement):

```json
{
  "greet_users": {
    "results": [...],
    "count": 10,
    "success_count": 10,
    "error_count": 0,
    "errors": null
  }
}
```

### Enhanced (after):

```json
{
  "greet_users": {
    "results": [...],
    "count": 10,
    "success_count": 10,
    "error_count": 0,
    "errors": null,
    "batch_metadata": {
      "parallel": true,
      "max_concurrent": 5,
      "max_retries": 1,
      "retry_wait": 0,
      "execution_mode": "parallel",
      "timing": {
        "total_items_ms": 234.56,
        "avg_item_ms": 23.46,
        "min_item_ms": 15.23,
        "max_item_ms": 45.67
      }
    }
  }
}
```

---

## What Appears in Trace File

The `shared_after` capture in `workflow_trace.py` will automatically include:

```json
{
  "nodes": [
    {
      "node_id": "greet_users",
      "node_type": "PflowBatchNode",
      "duration_ms": 250.12,
      "success": true,
      "shared_after": {
        "greet_users": {
          "results": [...],
          "count": 10,
          "success_count": 10,
          "error_count": 0,
          "errors": null,
          "batch_metadata": {
            "parallel": true,
            "max_concurrent": 5,
            "execution_mode": "parallel",
            "timing": {
              "total_items_ms": 234.56,
              "avg_item_ms": 23.46,
              "min_item_ms": 15.23,
              "max_item_ms": 45.67
            }
          }
        }
      }
    }
  ]
}
```

---

## Benefits

1. **Zero changes to tracing system** - uses existing `shared_after` capture
2. **Backward compatible** - adds new fields, doesn't change existing ones
3. **Rich debugging info** - timing stats, parallel mode, concurrency settings
4. **Automatic integration** - appears in all traces by default

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/pflow/runtime/batch_node.py` | Add timing tracking, enhance `post()` output |
| `tests/test_runtime/test_batch_node.py` | Add tests for new metadata fields |

---

## Test Cases to Add

1. `test_batch_output_includes_metadata` - verify metadata structure
2. `test_batch_metadata_parallel_mode` - verify parallel-specific fields
3. `test_batch_metadata_sequential_mode` - verify sequential-specific fields
4. `test_batch_timing_stats_calculated` - verify timing calculations
5. `test_batch_metadata_in_trace` - integration test with trace collector

---

## Estimated Effort

- Implementation: ~30 minutes
- Tests: ~20 minutes
- Total: ~50 minutes
