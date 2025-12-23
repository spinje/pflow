# Task 96 Implementation Progress Log

## 2024-12-23 - Starting Implementation

Reading through all documentation and understanding the approach...

### Key Understanding from Documentation Review

**What we're building**: Sequential batch processing (Phase 1 of data parallelism) that allows a single node to process multiple items from an array, with isolated contexts per item.

**Core pattern**: Inherit from PocketFlow's `BatchNode` to get per-item retry logic for free, using isolated shared store contexts (`item_shared = dict(shared)`).

**Critical architectural decisions verified**:
1. Batch wrapper goes between Namespace and Instrumented (needs raw shared dict access)
2. Option D chosen: Isolated copy per item for semantic correctness and parallel-readiness
3. MRO trick: `super(BatchNode, self)._exec(item)` skips BatchNode and calls Node._exec for retry
4. Error detection: Two layers - exceptions AND result dict "error" key

### Implementation Order
1. IR Schema - Add BATCH_CONFIG_SCHEMA
2. PflowBatchNode - Core class
3. Compiler integration - Insert wrapper at ~line 670
4. Workflow validation - Batch config validation
5. Integration tests - E2E tests
6. Edge cases & polish

---

## 2024-12-23 - Phase 1: IR Schema Extension

### Goal
Add `batch` configuration to the IR node schema so workflows can declare batch processing on nodes.

### Plan
1. Read current `ir_schema.py` to understand structure
2. Define `BATCH_CONFIG_SCHEMA` with required fields
3. Add `batch` property to NODE_SCHEMA
4. Write tests for schema validation

### Starting...

Reading `ir_schema.py`...

**Finding**: Node schema is defined inline within `FLOW_IR_SCHEMA` at lines 130-147
- Has `additionalProperties: false` (line 146) - must add `batch` to properties
- Current node properties: `id`, `type`, `purpose`, `params`

**Action**: Add `BATCH_CONFIG_SCHEMA` constant and reference it in node properties.

### Implementing IR Schema Changes...

**Changes made to `ir_schema.py`**:
1. Added `BATCH_CONFIG_SCHEMA` constant (lines 117-143) with:
   - `items` (required): Template reference pattern `^\$\{.+\}$`
   - `as` (optional, default "item"): Valid Python identifier pattern
   - `error_handling` (optional, default "fail_fast"): Enum ["fail_fast", "continue"]
   - `additionalProperties: false` to reject unknown fields

2. Added `batch` property to node schema (line 173)

3. Exported `BATCH_CONFIG_SCHEMA` from `src/pflow/core/__init__.py`

**Tests added to `test_ir_schema.py`** (11 new tests in `TestBatchConfig` class):
- ✅ `test_valid_batch_config_minimal` - Minimal valid config
- ✅ `test_valid_batch_config_all_fields` - All optional fields
- ✅ `test_valid_batch_config_fail_fast` - fail_fast error handling
- ✅ `test_batch_config_missing_items` - Missing required items
- ✅ `test_batch_config_items_not_template` - Invalid items format
- ✅ `test_batch_config_invalid_as_identifier` - Invalid identifier (123invalid)
- ✅ `test_batch_config_invalid_as_with_special_chars` - Invalid identifier (my-item)
- ✅ `test_batch_config_invalid_error_handling` - Invalid enum value
- ✅ `test_batch_config_extra_properties_rejected` - Unknown properties rejected
- ✅ `test_batch_config_with_complex_template` - Complex nested template path
- ✅ `test_valid_as_identifiers` - Various valid Python identifiers

**Results**:
- All 40 tests pass (29 existing + 11 new)
- `make check` passes (linting, type checking, dependency checks)

### Phase 1 Complete ✅

---

## 2024-12-23 - Phase 2: PflowBatchNode Implementation

### Goal
Create the core `PflowBatchNode` class that inherits from PocketFlow's `BatchNode`.

### Plan
1. Create new file `src/pflow/runtime/batch_node.py`
2. Implement `PflowBatchNode(BatchNode)` with:
   - `prep()` - resolve items template, store shared reference
   - `exec()` - process single item with isolated context
   - `_exec()` - override for continue mode error handling
   - `post()` - aggregate results into shared store
3. Add unit tests in `tests/test_runtime/test_batch_node.py`

### Implementation...

**Created `src/pflow/runtime/batch_node.py`** with:
- `PflowBatchNode(BatchNode)` class implementing isolated context pattern
- `prep()` - resolves items template via `TemplateResolver.resolve_value()`
- `exec(item)` - creates isolated `dict(shared)` copy, injects item alias, executes inner node
- `_exec(items)` - override for error handling modes, uses MRO trick for per-item retry
- `post()` - aggregates results with metadata (count, success_count, error_count, errors)
- `_extract_error()` - helper to detect error key in result dicts

**Key implementation details**:
- MRO trick: `super(BatchNode, self)._exec(item)` skips BatchNode and calls Node._exec for retry
- Shallow copy shares mutable objects (`__llm_calls__`) while isolating item-specific data
- Error detection handles both exceptions AND error keys in result dicts
- Fixed mypy error: Added explicit type handling in result capture

**Tests created in `tests/test_runtime/test_batch_node.py`** (30 tests):
- `TestPflowBatchNodeBasic`: 3 tests for basic operations
- `TestItemAliasInjection`: 2 tests for default and custom aliases
- `TestIsolatedContext`: 3 tests for context isolation
- `TestErrorHandling`: 4 tests for fail_fast and continue modes
- `TestResultStructure`: 3 tests for output structure
- `TestItemsResolution`: 5 tests for template resolution
- `TestComplexItems`: 2 tests for complex object items
- `TestExtractError`: 4 tests for error detection helper
- `TestDefaultValues`: 4 tests for configuration defaults

**Results**:
- All 30 tests pass
- `make check` passes (linting, type checking, dependency checks)

### Phase 2 Complete ✅

---

## 2024-12-23 - Phase 3: Compiler Integration

### Goal
Integrate `PflowBatchNode` into the compiler wrapper chain.

### Plan
1. Find the wrapper chain location in `compiler.py` (~line 670)
2. Insert batch wrapper between Namespace and Instrumented
3. Add tests for wrapper chain order

### Implementation...

**Modified `src/pflow/runtime/compiler.py`** (lines 671-689):
- Added batch wrapper insertion after namespace wrapping, before instrumented wrapping
- Added detailed debug logging with batch config details
- Critical comment explaining WHY batch must be OUTSIDE namespace wrapper

**Critical Bug Fix in `src/pflow/runtime/batch_node.py`**:
- Added `set_params()` method to forward params to inner_node chain
- Without this, TemplateAwareNodeWrapper never received template params like `${item}`
- Template resolution was returning None because params weren't reaching the wrapper

**Tests created in `tests/test_runtime/test_compiler_batch.py`** (14 tests):
- `TestBatchWrapperChain`: 3 tests verifying wrapper chain order
- `TestBatchConfigParsing`: 4 tests for config parsing
- `TestBatchExecutionIntegration`: 5 tests for end-to-end execution
- `TestBatchEdgeCases`: 2 tests for edge cases

**Key Insight - Wrapper Chain Order**:
```
Instrumented → PflowBatchNode → Namespace → Template → Actual
```
- Batch MUST be outside namespace so `shared["item"] = x` writes to root level
- If batch were inside namespace, it would write to `shared["node_id"]["item"]`
- Template resolution needs to find `${item}` at root level

**Results**:
- All 55 batch-related tests pass (30 batch_node + 14 compiler_batch + 11 schema)
- `make check` passes (linting, type checking, dependency checks)

### Phase 3 Complete ✅

---

## 2024-12-23 - Manual Verification

Ran end-to-end CLI test with real HTTP API:
```bash
uv run pflow examples/batch-test.json
```

**Test workflow**: HTTP node fetches 10 users from JSONPlaceholder API → Batch node greets each user by name.

**Result**: ✅ All 10 users processed correctly. Template `${item.name}` resolved for each user.

---

## 2024-12-23 - Summary

### Implementation Complete!

**Files Created**:
1. `src/pflow/runtime/batch_node.py` - PflowBatchNode class (275 lines)
2. `tests/test_runtime/test_batch_node.py` - 30 unit tests
3. `tests/test_runtime/test_compiler_batch.py` - 15 compiler integration tests
4. `scripts/test_batch_manual.py` - Manual verification script
5. `examples/batch-test.json` - Example batch workflow

**Files Modified**:
1. `src/pflow/core/ir_schema.py` - Added BATCH_CONFIG_SCHEMA
2. `src/pflow/core/__init__.py` - Exported BATCH_CONFIG_SCHEMA
3. `src/pflow/runtime/compiler.py` - Integrated batch wrapper
4. `tests/test_core/test_ir_schema.py` - Added 11 batch schema tests

**Total Tests**: 56 tests (11 schema + 30 unit + 15 integration)

---

## Key Insights and Hard-Won Understanding

### 1. Why Wrapper Chain Order Matters (Critical!)

**The Problem**: Where should PflowBatchNode be inserted in the wrapper chain?

**Initial confusion**: The handover docs mentioned "between Namespace and Instrumented" but didn't explain WHY this specific position matters.

**The insight**: Batch needs to inject `shared["item"] = current_item` at the ROOT level of the shared store. If batch were INSIDE the namespace wrapper:
- `shared["item"] = x` would write to `shared["node_id"]["item"]` (wrong!)
- Template resolution looking for `${item}` would fail

**Correct order** (execution flow, outer to inner):
```
Instrumented._run(shared)
  → PflowBatchNode._run(shared)           # Injects item at ROOT level
    → NamespacedNodeWrapper._run(shared)  # Creates proxy
      → TemplateAwareNodeWrapper._run(proxy)  # Resolves ${item}
        → ActualNode._run(proxy)
```

### 2. Why Template Resolution Works (NamespacedSharedStore Magic)

**The Question**: If batch injects `item` at root level, and NamespacedNodeWrapper creates a proxy, how does TemplateAwareNodeWrapper find `${item}`?

**The Answer**: `NamespacedSharedStore.keys()` returns BOTH namespace keys AND root keys:
```python
def keys(self) -> set[str]:
    namespace_keys = set(self._parent[self._namespace].keys())
    root_keys = set(self._parent.keys())
    root_keys.discard(self._namespace)
    return namespace_keys | root_keys  # Union!
```

When TemplateAwareNodeWrapper builds context with `dict(proxy)`, it gets all keys including `"item"` from root level.

### 3. The set_params Bug (Discovered During Implementation)

**The Bug**: Template resolution returned `None` for `${item}` even though item was correctly injected.

**Root Cause**: `PflowBatchNode` inherits `set_params()` from `BaseNode`:
```python
def set_params(self, params):
    self.params = params  # Only sets on self, doesn't forward!
```

The params containing `{"value": "${item}"}` never reached `TemplateAwareNodeWrapper`, so it had no templates to resolve.

**The Fix**: Override `set_params()` to forward to inner_node:
```python
def set_params(self, params):
    super().set_params(params)
    if hasattr(self.inner_node, "set_params"):
        self.inner_node.set_params(params)
```

### 4. MRO Trick for Per-Item Retry

**The Goal**: Each item should have independent retry logic (if one fails and retries, others aren't affected).

**The Trick**: `super(BatchNode, self)._exec(item)` skips `BatchNode._exec` and calls `Node._exec` directly:
```
MRO: PflowBatchNode → BatchNode → Node → BaseNode → object
           ↑ we're here   ↑ skip this  ↑ call this (has retry loop)
```

This gives us per-item retry for free from PocketFlow's Node class.

### 5. Why Shell Node Doesn't Work for Batch Input

**The Confusion**: Initial CLI test failed because `${create_list.stdout_json}` resolved to None.

**The Reality**: Shell node outputs a STRING, not a parsed array:
```python
shared["stdout"] = '["apple", "banana", "cherry"]\n'  # String!
# Batch needs:
shared["something"] = ["apple", "banana", "cherry"]   # Actual list!
```

**Working Solution**: HTTP node DOES parse JSON responses into Python objects:
```python
response_data = response.json()  # Returns actual list/dict
```

So `${fetch_users.response}` returns an actual Python list that batch can iterate over.

### 6. Shallow Copy Intentionally Shares Mutable Objects

**The Pattern**: `item_shared = dict(shared)` creates a shallow copy.

**Why Shallow**:
- Immutable values (strings, numbers) are isolated per item ✓
- Mutable objects like `__llm_calls__` list are SHARED across items ✓

This is intentional! LLM usage tracking needs to accumulate across all items.

### 7. Two-Layer Error Detection

**Layer 1**: Exceptions raised during `exec()` - caught in try/except

**Layer 2**: Error key in result dict - some nodes signal errors by writing to `result["error"]` instead of raising

Both must be checked to catch all error patterns across different node types.

---

## What Would Break This Implementation

1. **Changing wrapper chain order** - Batch must stay outside namespace
2. **Removing set_params forwarding** - Templates would stop resolving
3. **Using deep copy instead of shallow** - Would break `__llm_calls__` tracking
4. **Assuming all nodes output arrays** - Only some nodes (HTTP, future list-files) produce actual lists

---

## Phase 2: Parallel Batch Processing - NOT IMPLEMENTED

**Important clarification**: The term "data parallelism" in Task 96's title refers to the PATTERN (same operation on multiple items), NOT concurrent execution.

**Phase 1** (what we built): Sequential batch processing - items processed one at a time.

**Phase 2** (future work): Parallel batch processing - items processed concurrently using ThreadPoolExecutor or asyncio.

### Handover Document

Full research and implementation plan for Phase 2 is documented in:
**`.taskmaster/tasks/task_96/research/phase-2-parallel-batch-handover.md`**

This document covers:
- Implementation options (ThreadPoolExecutor vs asyncio.to_thread)
- Thread safety considerations
- Error handling with concurrency
- Relationship to Task 39 (task parallelism)
- Open questions for next agent

### Relationship to Task 39

| Task | Pattern | What Runs Concurrently |
|------|---------|------------------------|
| Task 96 Phase 2 | Data parallelism | Same node, different items |
| Task 39 | Task parallelism | Different nodes, same data |

Both would use the same threading infrastructure. Implementing Phase 2 first establishes patterns Task 39 can reuse.
