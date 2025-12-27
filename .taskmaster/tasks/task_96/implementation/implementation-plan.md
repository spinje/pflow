# Task 96 Implementation Plan: Batch Processing

**Version**: 1.1
**Based on**: task-96-spec.md v1.2.0 (Option D: Isolated Shared Store Per Item)
**Date**: 2024-12-23

---

## Changelog

- **v1.1** (2024-12-23): Added error detection for non-exception errors (dict with "error" key), added `_extract_error()` helper, updated success counting logic, clarified test criteria interpretation

---

## Overview

Implement sequential batch processing by inheriting from PocketFlow's `BatchNode`, gaining per-item retry logic for free while using isolated shared store contexts.

**Core Pattern** (using PocketFlow's prep/exec/post lifecycle):
```python
class PflowBatchNode(BatchNode):
    def prep(self, shared):
        self._shared = shared
        return resolve_items(shared)  # BatchNode iterates over this

    def exec(self, item):  # Called per item with retry logic
        item_shared = dict(self._shared)  # Isolated context
        item_shared["item"] = item
        item_shared[node_id] = {}
        inner_node._run(item_shared)
        return item_shared.get(node_id, {})

    def post(self, shared, prep_res, exec_res):  # exec_res is list
        shared[node_id] = {"results": exec_res, ...}
```

**Benefit**: Each item automatically gets PocketFlow's retry logic via `Node._exec()`.

---

## Phase 1: Schema & Validation

### 1.1 IR Schema Extension

**File**: `src/pflow/core/ir_schema.py`

**Changes**:
1. Define `BATCH_CONFIG_SCHEMA`:
```python
BATCH_CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "string",
            "pattern": r"^\$\{.+\}$",  # Must be template
            "description": "Template reference to array of items"
        },
        "as": {
            "type": "string",
            "pattern": r"^[a-zA-Z_][a-zA-Z0-9_]*$",  # Valid identifier
            "default": "item",
            "description": "Variable name for current item"
        },
        "error_handling": {
            "type": "string",
            "enum": ["fail_fast", "continue"],
            "default": "fail_fast",
            "description": "How to handle per-item errors"
        }
    },
    "required": ["items"],
    "additionalProperties": False
}
```

2. Add `batch` to `NODE_SCHEMA["properties"]`:
```python
"batch": BATCH_CONFIG_SCHEMA
```

**Tests**: `tests/test_core/test_ir_schema.py`
- Valid batch config passes validation
- Missing `items` fails
- Invalid `items` pattern fails
- Invalid `as` identifier fails
- Invalid `error_handling` value fails

### 1.2 Workflow Validation

**File**: `src/pflow/core/workflow_validator.py`

**Changes**:
1. Add `_validate_batch_config()` function:
   - Verify `items` template references existing node output
   - Verify `items` template resolves to array (at validation time, check if referenced node's output type is array)

2. Integrate into `validate_workflow()` pipeline

**Tests**: `tests/test_core/test_workflow_validator.py`
- Batch items referencing valid upstream node passes
- Batch items referencing non-existent node fails
- Batch items referencing downstream node fails (forward reference)

---

## Phase 2: Core Implementation

### 2.1 PflowBatchNode

**File**: `src/pflow/runtime/batch_node.py` (NEW)

```python
"""Batch processing using PocketFlow's BatchNode pattern."""

from typing import Any
from pocketflow import BatchNode
from pflow.runtime.template_resolver import TemplateResolver


class PflowBatchNode(BatchNode):
    """Batch node using PocketFlow's prep/exec/post lifecycle with isolated contexts."""

    def __init__(self, inner_node: Any, node_id: str, batch_config: dict[str, Any]):
        super().__init__()  # Initialize params, successors from BaseNode
        self.inner_node = inner_node
        self.node_id = node_id
        self.items_template = batch_config["items"]
        self.item_alias = batch_config.get("as", "item")
        self.error_handling = batch_config.get("error_handling", "fail_fast")
        self._shared: dict[str, Any] = {}
        self._errors: list[dict[str, Any]] = []

    def prep(self, shared: dict[str, Any]) -> list[Any]:
        """Return items list - BatchNode will iterate over this."""
        self._shared = shared
        var_path = self.items_template.strip()[2:-1]  # "${x}" -> "x"
        items = TemplateResolver.resolve_value(var_path, shared)
        if not isinstance(items, list):
            raise ValueError(f"Batch items must be array, got {type(items)}")
        return items

    def _extract_error(self, result: Any) -> str | None:
        """Extract error message from result dict if present.

        Nodes signal errors in two ways:
        1. Exceptions (caught by retry logic, then re-raised or handled by exec_fallback)
        2. Error key in result dict (e.g., {"error": "Error: Could not read file..."})

        Returns error message string if error detected, None otherwise.
        """
        if not isinstance(result, dict):
            return None
        error = result.get("error")
        if error:
            return str(error)
        return None

    def _exec(self, items: list[Any]) -> list[Any]:
        """Override to support error_handling: continue and detect errors in results.

        Error detection handles two cases:
        1. Exceptions raised during exec() - caught in try/except
        2. Error key in result dict - checked after successful exec()
        """
        self._errors = []
        results = []
        for i, item in enumerate(items):
            try:
                # super(BatchNode, self)._exec gives us per-item retry logic from Node._exec!
                result = super(BatchNode, self)._exec(item)

                # Check if result indicates an error (node wrote to error key)
                error_msg = self._extract_error(result)
                if error_msg:
                    if self.error_handling == "fail_fast":
                        raise RuntimeError(f"Item {i} failed: {error_msg}")
                    self._errors.append({"index": i, "item": item, "error": error_msg})

                results.append(result)
            except Exception as e:
                if self.error_handling == "fail_fast":
                    raise
                self._errors.append({"index": i, "item": item, "error": str(e)})
                results.append(None)
        return results

    def exec(self, item: Any) -> dict[str, Any]:
        """Process single item with isolated context. Called with retry logic."""
        item_shared = dict(self._shared)
        item_shared[self.item_alias] = item
        item_shared[self.node_id] = {}
        self.inner_node._run(item_shared)
        return item_shared.get(self.node_id, {})

    def post(self, shared: dict[str, Any], prep_res: list, exec_res: list) -> str:
        """Aggregate results into shared store.

        Success counting logic:
        - Exception during exec() → result is None → not a success
        - Result has error key → counted in self._errors → not a success
        - Result is valid dict without error → success
        """
        # Count successes: non-None results without error keys
        success_count = sum(
            1 for r in exec_res
            if r is not None and not self._extract_error(r)
        )

        shared[self.node_id] = {
            "results": exec_res,
            "count": len(exec_res),
            "success_count": success_count,
            "error_count": len(self._errors),
            "errors": self._errors if self._errors else None
        }
        return "default"
```

**Tests**: `tests/test_runtime/test_batch_node.py`

| Test | Description |
|------|-------------|
| `test_batch_empty_items` | Empty array → `{results: [], count: 0, ...}` |
| `test_batch_single_item` | Single item processed correctly |
| `test_batch_multiple_items` | Multiple items in order |
| `test_batch_item_alias_injection` | `${item}` visible in template |
| `test_batch_custom_alias` | `as: "file"` → `${file}` works |
| `test_batch_isolated_context` | Items don't pollute each other |
| `test_batch_fail_fast_exception` | Exception stops execution |
| `test_batch_continue_exception` | Exception recorded, continues |
| `test_batch_fail_fast_error_in_result` | Result with error key triggers fail_fast |
| `test_batch_continue_error_in_result` | Result with error key recorded, continues |
| `test_batch_result_structure` | Output has results, count, success_count, error_count |
| `test_batch_items_not_array` | ValueError for non-array |
| `test_batch_items_none` | ValueError for None |
| `test_batch_special_keys_shared` | `__llm_calls__` accumulates across items |
| `test_batch_per_item_retry` | Transient failure retries before failing |
| `test_batch_success_count_excludes_errors` | success_count excludes items with error key |
| `test_batch_extract_error_helper` | `_extract_error()` correctly detects error key |

### 2.2 Error Detection Clarification

The spec mentions "Error:" prefix detection, but in practice nodes write errors to a dict. Here's how to interpret the spec's test criteria:

| Spec Language | Actual Implementation |
|---------------|----------------------|
| "Item returns `Error:...`" | `result.get("error")` is truthy |
| "Item result is `None`" | Exception was caught, result set to `None` |
| "Error: prefix detected" | Check `result.get("error")` for any truthy value |
| "Treated as success" | `result` is dict without error key (even if empty `{}`) |

**Two error sources**:
1. **Exceptions**: Caught in `_exec` try/except → result is `None`
2. **Error in result dict**: Node completed but wrote error → result has `{"error": "..."}` key

**Both are recorded in `self._errors` and counted in `error_count`.**

---

## Phase 3: Compiler Integration

### 3.1 Compiler Changes

**File**: `src/pflow/runtime/compiler.py`

**Location**: `_create_single_node()` function, around line 670

**Changes**:
```python
# After namespace wrapping (line ~669):
if enable_namespacing:
    node_instance = NamespacedNodeWrapper(node_instance, node_id)

# NEW: Apply batch node if configured
batch_config = node_data.get("batch")
if batch_config:
    from pflow.runtime.batch_node import PflowBatchNode
    logger.debug(
        f"Wrapping node '{node_id}' for batch processing",
        extra={"phase": "node_instantiation", "node_id": node_id}
    )
    node_instance = PflowBatchNode(node_instance, node_id, batch_config)

# Before instrumentation wrapping (line ~676):
node_instance = InstrumentedNodeWrapper(...)
```

**Tests**: `tests/test_runtime/test_compiler.py`
- Batch node gets PflowBatchNode applied
- Non-batch node unchanged
- Wrapper chain order correct: `Instrumented > PflowBatchNode > Namespace > Template > Actual`

---

## Phase 4: Integration Testing

### 4.1 End-to-End Tests

**File**: `tests/test_integration/test_batch_workflows.py` (NEW)

| Test | Description |
|------|-------------|
| `test_batch_workflow_simple` | Single batch node, verify results |
| `test_batch_workflow_chain` | Batch node → downstream node using `${batch.results}` |
| `test_batch_workflow_multiple_batches` | Two batch nodes in sequence |
| `test_batch_with_llm_node` | Batch with mocked LLM, verify LLM tracking |
| `test_batch_complex_items` | Items are objects with nested fields |
| `test_batch_template_nested_access` | `${item.data.field}` resolves correctly |
| `test_batch_results_downstream` | `${batch.results[0].response}` works |

### 4.2 Error Scenario Tests

| Test | Description |
|------|-------------|
| `test_batch_partial_failure_continue` | Some items fail, others succeed |
| `test_batch_all_fail_continue` | All items fail, error array populated |
| `test_batch_first_item_fails_fast` | First item fails, no further execution |
| `test_batch_invalid_items_template` | Template doesn't resolve to array |

---

## Phase 5: Edge Cases & Polish

### 5.1 Edge Case Handling

1. **Empty batch**: Should produce `{results: [], count: 0, ...}`
2. **None in items array**: Each None is a valid item to process
3. **Large batch**: Memory is O(n), no special handling needed
4. **Nested objects as items**: Should work naturally with template resolution

### 5.2 Metrics & Tracing

**Consideration**: InstrumentedNodeWrapper wraps BatchNodeWrapper, so:
- Batch node appears as single execution in metrics
- Duration is total batch time
- LLM calls from all items accumulate in `__llm_calls__`

**Future enhancement**: Add batch-specific metrics (per-item timing, batch size)

---

## Implementation Order

```
Step 1: IR Schema (BATCH_CONFIG_SCHEMA)
        └── Tests for schema validation

Step 2: PflowBatchNode class
        └── Unit tests for batch node logic

Step 3: Compiler integration
        └── Tests for wrapper chain

Step 4: Workflow validation
        └── Tests for batch validation

Step 5: Integration tests
        └── End-to-end workflow tests

Step 6: Edge cases & polish
        └── Additional test coverage
```

---

## Files Summary

| File | Action | Description |
|------|--------|-------------|
| `src/pflow/core/ir_schema.py` | Modify | Add BATCH_CONFIG_SCHEMA, add to NODE_SCHEMA |
| `src/pflow/runtime/batch_node.py` | Create | PflowBatchNode(BatchNode) class |
| `src/pflow/runtime/compiler.py` | Modify | Apply PflowBatchNode in wrapper chain |
| `src/pflow/core/workflow_validator.py` | Modify | Add batch config validation |
| `tests/test_core/test_ir_schema.py` | Modify | Add batch schema tests |
| `tests/test_runtime/test_batch_node.py` | Create | Unit tests for PflowBatchNode |
| `tests/test_runtime/test_compiler.py` | Modify | Add batch wrapper chain tests |
| `tests/test_core/test_workflow_validator.py` | Modify | Add batch validation tests |
| `tests/test_integration/test_batch_workflows.py` | Create | E2E batch workflow tests |

---

## Success Criteria

From spec v1.2.0 (updated with v1.1 alterations):

1. ✅ `batch` configuration added to IR schema
2. ✅ Sequential batch execution works correctly
3. ✅ Error handling modes work (fail_fast, continue)
4. ✅ Template resolution works with item alias (`${file}`, `${item.name}`)
5. ✅ Results accessible as `${node_id.results}` array
6. ✅ Isolated contexts prevent cross-item pollution
7. ✅ Special keys (`__llm_calls__`) accumulate correctly
8. ✅ Per-item retry logic works (from PocketFlow's Node._exec)
9. ✅ Error detection works for both exceptions AND error keys in result dicts
10. ✅ success_count correctly excludes items with errors (not just None results)

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Shallow copy doesn't isolate enough | Low | Deep copy if needed (perf tradeoff) |
| Template resolution fails for item alias | Low | Test case #8, #26 verify |
| Metrics show wrong data for batch | Medium | Document aggregate behavior |
| Large batches cause memory issues | Low | Document O(n) constraint |
| Node uses non-standard error key | Low | `_extract_error()` checks standard "error" key; can extend if needed |
| Error detection misses edge cases | Low | Two-layer detection (exceptions + error key) covers all known patterns |

---

## Not In Scope (Phase 2)

- Parallel execution (`parallel: true`, `max_concurrent`)
- Async wrapper support
- Per-item metrics/tracing
- Nested batch (batch within batch)
