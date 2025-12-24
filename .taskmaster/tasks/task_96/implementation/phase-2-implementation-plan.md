# Task 96 Phase 2: Implementation Plan

**Date**: 2024-12-23
**Status**: Ready for implementation
**Prerequisites**: Phase 1-3 complete (sequential batch processing)

---

## Overview

Phase 2 adds parallel batch processing to the existing sequential implementation. The key changes are:

1. **Change inheritance**: `BatchNode` → `Node` (avoids `self.cur_retry` race condition)
2. **Thread-safe retry**: Local `retry` variable instead of `self.cur_retry`
3. **Deep copy per thread**: Avoids `inner_node.params` race condition in TemplateAwareNodeWrapper
4. **Same code path**: `_exec_single()` used by both sequential and parallel

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/pflow/core/ir_schema.py` | Add `parallel`, `max_concurrent`, `max_retries`, `retry_wait` to BATCH_CONFIG_SCHEMA |
| `src/pflow/runtime/batch_node.py` | Refactor to inherit from `Node`, add parallel execution |
| `tests/test_core/test_ir_schema.py` | Add tests for new schema fields |
| `tests/test_runtime/test_batch_node.py` | Add Phase 2 tests for parallel execution |

---

## Step 1: Update IR Schema

**File**: `src/pflow/core/ir_schema.py`

**Current BATCH_CONFIG_SCHEMA** (lines 119-143):
```python
BATCH_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {...},
        "as": {...},
        "error_handling": {...},
    },
    ...
}
```

**Add these properties**:

```python
BATCH_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Configuration for batch processing of multiple items",
    "properties": {
        "items": {
            "type": "string",
            "pattern": r"^\$\{.+\}$",
            "description": "Template reference to array of items to process (e.g., '${node.files}')",
        },
        "as": {
            "type": "string",
            "pattern": r"^[a-zA-Z_][a-zA-Z0-9_]*$",
            "default": "item",
            "description": "Variable name for current item in templates (default: 'item')",
        },
        "error_handling": {
            "type": "string",
            "enum": ["fail_fast", "continue"],
            "default": "fail_fast",
            "description": "How to handle per-item errors: 'fail_fast' stops on first error, 'continue' processes all items",
        },
        # NEW Phase 2 fields:
        "parallel": {
            "type": "boolean",
            "default": False,
            "description": "Enable concurrent execution of items (default: sequential)",
        },
        "max_concurrent": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100,
            "default": 10,
            "description": "Maximum concurrent workers when parallel=true (default: 10)",
        },
        "max_retries": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10,
            "default": 1,
            "description": "Maximum retry attempts per item (default: 1, no retry)",
        },
        "retry_wait": {
            "type": "number",
            "minimum": 0,
            "default": 0,
            "description": "Seconds to wait between retries (default: 0)",
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}
```

**Tests to add** (`tests/test_core/test_ir_schema.py`):

```python
def test_batch_config_parallel_true(self):
    """Test valid batch config with parallel execution enabled."""
    ir = {
        "ir_version": "0.1.0",
        "nodes": [{
            "id": "batch_node",
            "type": "llm",
            "batch": {
                "items": "${data}",
                "parallel": True,
                "max_concurrent": 5,
            },
        }],
    }
    validate_ir(ir)

def test_batch_config_max_concurrent_bounds(self):
    """Test max_concurrent validation (1-100)."""
    # Valid: 1
    # Valid: 100
    # Invalid: 0
    # Invalid: 101

def test_batch_config_max_retries_bounds(self):
    """Test max_retries validation (1-10)."""
    # Valid: 1
    # Valid: 10
    # Invalid: 0
    # Invalid: 11

def test_batch_config_retry_wait_non_negative(self):
    """Test retry_wait must be >= 0."""
    # Valid: 0
    # Valid: 1.5
    # Invalid: -1
```

---

## Step 2: Refactor PflowBatchNode

**File**: `src/pflow/runtime/batch_node.py`

### 2.1 Change Inheritance and Imports

**Before**:
```python
from pocketflow import BatchNode

class PflowBatchNode(BatchNode):
```

**After**:
```python
import copy
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from pocketflow import Node

class PflowBatchNode(Node):
```

### 2.2 Update __init__ to Parse New Config Fields

**Current** (lines 75-95):
```python
def __init__(self, inner_node: Any, node_id: str, batch_config: dict[str, Any]):
    super().__init__()
    self.inner_node = inner_node
    self.node_id = node_id
    self.items_template = batch_config["items"]
    self.item_alias = batch_config.get("as", "item")
    self.error_handling = batch_config.get("error_handling", "fail_fast")
    self._shared: dict[str, Any] = {}
    self._errors: list[dict[str, Any]] = []
```

**After**:
```python
def __init__(self, inner_node: Any, node_id: str, batch_config: dict[str, Any]):
    super().__init__()
    self.inner_node = inner_node
    self.node_id = node_id

    # Batch configuration
    self.items_template = batch_config["items"]
    self.item_alias = batch_config.get("as", "item")
    self.error_handling = batch_config.get("error_handling", "fail_fast")

    # Phase 2: Parallel execution config
    self.parallel = batch_config.get("parallel", False)
    self.max_concurrent = batch_config.get("max_concurrent", 10)
    self.max_retries = batch_config.get("max_retries", 1)
    self.retry_wait = batch_config.get("retry_wait", 0)

    # Instance state for current batch execution
    self._shared: dict[str, Any] = {}
    self._errors: list[dict[str, Any]] = []
```

### 2.3 Add _exec_single() with Thread-Safe Retry

This replaces the MRO trick with explicit, thread-safe retry logic.

```python
def _exec_single(self, idx: int, item: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Execute single item with thread-safe retry logic.

    Uses local `retry` variable instead of `self.cur_retry` to avoid race conditions
    when multiple threads execute concurrently.

    Args:
        idx: Index of item in original list (for error reporting)
        item: The item to process

    Returns:
        Tuple of (result, error_info):
        - On success: (result_dict, None)
        - On error with continue mode: (None, {"index": idx, "item": item, "error": str})
        - On error with fail_fast mode: raises exception
    """
    last_exception: Exception | None = None

    for retry in range(self.max_retries):
        try:
            # Create isolated context for this item
            item_shared = dict(self._shared)
            item_shared[self.node_id] = {}
            item_shared[self.item_alias] = item

            # Execute inner node
            self.inner_node._run(item_shared)

            # Capture result from inner node's namespace
            result = item_shared.get(self.node_id)
            if result is None:
                result = {}
            elif not isinstance(result, dict):
                result = {"value": result}

            # Check for error in result dict
            error_msg = self._extract_error(result)
            if error_msg:
                if self.error_handling == "fail_fast":
                    raise RuntimeError(f"Item {idx} failed: {error_msg}")
                return (result, {"index": idx, "item": item, "error": error_msg})

            return (result, None)

        except Exception as e:
            last_exception = e
            if retry < self.max_retries - 1:
                if self.retry_wait > 0:
                    time.sleep(self.retry_wait)
                logger.debug(
                    f"Batch item {idx} retry {retry + 1}/{self.max_retries}: {e}",
                    extra={"node_id": self.node_id, "item_index": idx, "retry": retry + 1},
                )
                continue
            break

    # All retries exhausted
    if self.error_handling == "fail_fast":
        raise last_exception or RuntimeError(f"Item {idx} failed after {self.max_retries} retries")

    return (None, {"index": idx, "item": item, "error": str(last_exception)})
```

### 2.4 Add _exec_single_with_node() for Parallel (Deep Copy)

For parallel execution, we need to deep copy the node chain to avoid the TemplateAwareNodeWrapper race condition.

```python
def _exec_single_with_node(
    self, idx: int, item: Any, item_shared: dict[str, Any], thread_node: Any
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Execute single item with provided node (for parallel execution with deep copy).

    Args:
        idx: Index of item in original list
        item: The item to process
        item_shared: Pre-created isolated shared store for this item
        thread_node: Deep-copied node chain for thread isolation

    Returns:
        Tuple of (result, error_info)
    """
    last_exception: Exception | None = None

    for retry in range(self.max_retries):
        try:
            # Execute the thread-local node copy
            thread_node._run(item_shared)

            # Capture result
            result = item_shared.get(self.node_id)
            if result is None:
                result = {}
            elif not isinstance(result, dict):
                result = {"value": result}

            # Check for error in result dict
            error_msg = self._extract_error(result)
            if error_msg:
                return (result, {"index": idx, "item": item, "error": error_msg})

            return (result, None)

        except Exception as e:
            last_exception = e
            if retry < self.max_retries - 1:
                if self.retry_wait > 0:
                    time.sleep(self.retry_wait)
                continue
            break

    return (None, {"index": idx, "item": item, "error": str(last_exception)})
```

### 2.5 Add _exec_sequential()

```python
def _exec_sequential(self, items: list[Any]) -> list[dict[str, Any] | None]:
    """Execute items sequentially using _exec_single.

    Args:
        items: List of items to process

    Returns:
        List of results in same order as input
    """
    results: list[dict[str, Any] | None] = []

    for idx, item in enumerate(items):
        result, error = self._exec_single(idx, item)
        results.append(result)
        if error:
            self._errors.append(error)

    return results
```

### 2.6 Add _exec_parallel()

```python
def _exec_parallel(self, items: list[Any]) -> list[dict[str, Any] | None]:
    """Execute items in parallel using ThreadPoolExecutor.

    Each thread gets:
    - Shallow copy of shared store (shares __llm_calls__ list)
    - Deep copy of node chain (avoids TemplateAwareNodeWrapper race condition)

    Args:
        items: List of items to process

    Returns:
        List of results in same order as input (preserves ordering)
    """
    results: list[dict[str, Any] | None] = [None] * len(items)
    pending_errors: list[dict[str, Any]] = []

    def process_item(idx: int, item: Any) -> tuple[int, dict[str, Any] | None, dict[str, Any] | None]:
        """Process single item in thread. Returns (index, result, error)."""
        # Create isolated shared store (shallow copy shares __llm_calls__)
        item_shared = dict(self._shared)
        item_shared[self.node_id] = {}
        item_shared[self.item_alias] = item

        # CRITICAL: Deep copy node chain to avoid TemplateAwareNodeWrapper race condition
        # Each thread gets its own copy of the wrapper chain
        thread_node = copy.deepcopy(self.inner_node)

        # Execute with thread-local node
        result, error = self._exec_single_with_node(idx, item, item_shared, thread_node)
        return (idx, result, error)

    with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
        # Submit all items
        future_to_idx = {
            executor.submit(process_item, idx, item): idx
            for idx, item in enumerate(items)
        }

        # Collect results as they complete
        for future in as_completed(future_to_idx):
            try:
                idx, result, error = future.result()
                results[idx] = result

                if error:
                    pending_errors.append(error)
                    if self.error_handling == "fail_fast":
                        # Cancel remaining futures (only cancels not-yet-started)
                        for f in future_to_idx:
                            f.cancel()
                        # Raise immediately
                        raise RuntimeError(error["error"])

            except RuntimeError:
                # Re-raise fail_fast errors
                raise
            except Exception as e:
                # Unexpected executor error
                idx = future_to_idx[future]
                pending_errors.append({
                    "index": idx,
                    "item": items[idx],
                    "error": f"Executor error: {e}",
                })
                if self.error_handling == "fail_fast":
                    raise

    # Merge errors (single-threaded, safe)
    self._errors.extend(pending_errors)

    return results
```

### 2.7 Update _exec() to Dispatch

**Replace current _exec()** (lines 169-210) with:

```python
def _exec(self, items: list[Any]) -> list[dict[str, Any] | None]:
    """Execute batch processing - dispatches to sequential or parallel.

    Args:
        items: List of items from prep()

    Returns:
        List of results in same order as input
    """
    self._errors = []

    if not items:
        return []

    if self.parallel:
        logger.debug(
            f"Batch node '{self.node_id}' executing {len(items)} items in parallel "
            f"(max_concurrent={self.max_concurrent})",
            extra={"node_id": self.node_id, "parallel": True, "max_concurrent": self.max_concurrent},
        )
        return self._exec_parallel(items)
    else:
        logger.debug(
            f"Batch node '{self.node_id}' executing {len(items)} items sequentially",
            extra={"node_id": self.node_id, "parallel": False},
        )
        return self._exec_sequential(items)
```

### 2.8 Remove exec() Method

The current `exec()` method (lines 212-250) is called by the MRO trick. With the new design, `_exec_single()` handles item execution directly.

**Remove** the `exec()` method entirely - it's no longer needed.

### 2.9 Update Module Docstring

Update the docstring at the top of the file to reflect Phase 2 capabilities:

```python
"""Batch processing node with sequential and parallel execution.

This module provides PflowBatchNode, which wraps any pflow node to process
multiple items. Supports both sequential and parallel execution modes.

Key Design Decisions:
- **Inherits from Node (not BatchNode)**: Cleaner design, avoids MRO tricks
- **Thread-safe retry**: Uses local `retry` variable instead of `self.cur_retry`
- **Deep copy for parallel**: Each thread gets its own node chain copy to avoid
  TemplateAwareNodeWrapper race condition on `inner_node.params`
- **Isolated context per item**: Each item gets `item_shared = dict(shared)`

IR Syntax:
    ```json
    {
      "id": "summarize",
      "type": "llm",
      "batch": {
        "items": "${list_files.files}",
        "as": "file",
        "parallel": true,
        "max_concurrent": 5,
        "max_retries": 3,
        "retry_wait": 1.0,
        "error_handling": "continue"
      },
      "params": {"prompt": "Summarize: ${file}"}
    }
    ```

Output Structure:
    ```python
    shared["summarize"] = {
        "results": [...],      # Array of results in input order
        "count": 3,            # Total items processed
        "success_count": 2,    # Items without errors
        "error_count": 1,      # Items with errors
        "errors": [...]        # Error details (or None if no errors)
    }
    ```

Thread Safety:
    - Sequential mode: Single-threaded, no concerns
    - Parallel mode:
      - Each thread gets deep copy of node chain (isolates TemplateAwareNodeWrapper)
      - Shallow copy of shared store (shares __llm_calls__ list, GIL-protected)
      - Local retry counter (avoids self.cur_retry race condition)
"""
```

---

## Step 3: Run Phase 1 Tests (Verify No Regressions)

After refactoring, run existing tests:

```bash
uv run pytest tests/test_runtime/test_batch_node.py -v
uv run pytest tests/test_runtime/test_compiler_batch.py -v
uv run pytest tests/test_core/test_ir_schema.py::TestBatchConfig -v
```

**Expected**: All 56 existing tests should pass with the new inheritance.

---

## Step 4: Add Phase 2 Tests

**File**: `tests/test_runtime/test_batch_node.py`

### 4.1 Parallel Execution Tests

```python
class TestParallelExecution:
    """Tests for parallel batch execution (Phase 2)."""

    def test_parallel_execution_basic(self):
        """All items execute and results collected in parallel mode."""

    def test_parallel_preserves_order(self):
        """Results are in same order as input items regardless of completion order."""

    def test_parallel_with_max_concurrent_1(self):
        """max_concurrent=1 effectively runs sequentially."""

    def test_parallel_with_max_concurrent_2(self):
        """max_concurrent=2 limits concurrent workers."""

    def test_parallel_empty_list(self):
        """Empty input returns empty results in parallel mode."""

    def test_parallel_single_item(self):
        """Single item works in parallel mode."""
```

### 4.2 Error Handling in Parallel

```python
class TestParallelErrorHandling:
    """Tests for error handling in parallel mode."""

    def test_parallel_fail_fast_stops_submission(self):
        """First error in fail_fast mode cancels pending work."""

    def test_parallel_continue_collects_all_errors(self):
        """All items run even when some fail with continue mode."""

    def test_parallel_error_preserves_successful_results(self):
        """Successful items before error are captured."""
```

### 4.3 Retry in Parallel

```python
class TestParallelRetry:
    """Tests for retry logic in parallel mode."""

    def test_parallel_retry_success_after_failure(self):
        """Item succeeds on retry in parallel mode."""

    def test_parallel_retry_all_attempts_exhausted(self):
        """Error reported after all retries fail."""

    def test_parallel_retry_wait_respected(self):
        """retry_wait delay is honored between retries."""

    def test_parallel_retry_isolated_per_item(self):
        """Each item has independent retry counter (no race condition)."""
```

### 4.4 Thread Safety Verification

```python
class TestThreadSafety:
    """Tests verifying thread safety of parallel execution."""

    def test_isolated_context_per_item(self):
        """Each item gets its own shared store copy."""

    def test_llm_calls_accumulated_correctly(self):
        """__llm_calls__ list correctly tracks all calls from all threads."""

    def test_no_cross_item_pollution(self):
        """Item A's data doesn't leak into Item B's context."""

    def test_template_resolution_isolated(self):
        """Template params don't race between threads (deep copy works)."""
```

### 4.5 Integration Tests

```python
class TestParallelIntegration:
    """Integration tests for parallel batch with real workflow."""

    def test_parallel_vs_sequential_same_results(self):
        """Parallel and sequential produce identical results."""

    def test_parallel_with_template_resolution(self):
        """Templates resolve correctly in parallel context."""

    def test_parallel_with_namespacing(self):
        """Namespaced outputs work correctly in parallel."""
```

---

## Step 5: Integration Test with CLI

Create/update example workflow:

**File**: `examples/batch-test-parallel.json`

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "fetch_users",
      "type": "http",
      "purpose": "Fetch a list of users from JSONPlaceholder API",
      "params": {
        "url": "https://jsonplaceholder.typicode.com/users",
        "method": "GET"
      }
    },
    {
      "id": "greet_users",
      "type": "shell",
      "purpose": "Greet each user by name (parallel)",
      "batch": {
        "items": "${fetch_users.response}",
        "as": "user",
        "parallel": true,
        "max_concurrent": 5
      },
      "params": {
        "command": "echo \"Hello, ${user.name}!\""
      }
    }
  ],
  "edges": [
    {"from": "fetch_users", "to": "greet_users"}
  ]
}
```

Run with:
```bash
uv run pflow examples/batch-test-parallel.json
```

---

## Acceptance Criteria

### Must Pass

- [ ] All 56 existing Phase 1 tests pass after refactor
- [ ] New IR schema fields validate correctly
- [ ] `parallel: false` (default) behaves identically to Phase 1
- [ ] `parallel: true` executes items concurrently
- [ ] Result order preserved regardless of completion order
- [ ] `max_concurrent` limits concurrent workers
- [ ] `max_retries` and `retry_wait` work in both modes
- [ ] `fail_fast` cancels pending futures on first error
- [ ] `continue` collects all errors
- [ ] `__llm_calls__` accumulates correctly in parallel
- [ ] No race conditions in retry counter
- [ ] No race conditions in template resolution
- [ ] `make check` passes (linting, type checking)
- [ ] `make test` passes (all tests)

### Nice to Have

- [ ] Performance test showing parallel speedup
- [ ] Example workflow demonstrating parallel batch

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Phase 1 tests break from inheritance change | Run tests immediately after refactor, before adding Phase 2 code |
| Deep copy fails for some node type | All platform nodes verified stateless and copyable |
| Race condition in error collection | Collect errors per-thread, merge in main thread |
| `__llm_calls__` not thread-safe | CPython GIL protects list.append(); verified in research |

---

## Implementation Order

1. **Update IR Schema** (~15 min)
   - Add new properties to BATCH_CONFIG_SCHEMA
   - Add schema validation tests

2. **Refactor PflowBatchNode** (~45 min)
   - Change inheritance to Node
   - Add `_exec_single()` with local retry
   - Add `_exec_sequential()` using `_exec_single()`
   - Update `_exec()` to dispatch
   - Remove old `exec()` method
   - Update docstrings

3. **Run Phase 1 Tests** (~5 min)
   - Verify no regressions from refactor

4. **Add Parallel Execution** (~30 min)
   - Add `_exec_single_with_node()`
   - Add `_exec_parallel()`
   - Parse new config in `__init__()`

5. **Add Phase 2 Tests** (~45 min)
   - Parallel execution tests
   - Error handling tests
   - Retry tests
   - Thread safety tests

6. **Integration Testing** (~15 min)
   - End-to-end CLI test
   - Verify `make check` and `make test` pass

**Estimated total**: ~2.5 hours

---

## Summary

This implementation plan delivers parallel batch processing by:

1. **Inheriting from Node** instead of BatchNode - cleaner, no MRO tricks
2. **Local retry variable** - thread-safe, no `self.cur_retry` race condition
3. **Deep copy per thread** - isolates TemplateAwareNodeWrapper params mutation
4. **Same `_exec_single()` for both modes** - consistent code paths

The design has been thoroughly verified against the codebase and is ready for implementation.
