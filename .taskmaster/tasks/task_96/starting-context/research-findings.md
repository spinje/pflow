# Task 96 Research Findings: Support Batch Processing in Workflows

**Research Date**: 2024-12-22
**Status**: Complete
**Confidence Level**: High (all critical paths verified against source code)

---

## Executive Summary

This document synthesizes findings from 8 parallel research investigations into the pflow codebase. The goal was to understand how to implement batch processing (data parallelism) by exposing PocketFlow's existing `BatchNode` and `AsyncParallelBatchNode` in pflow's IR schema.

**Key Finding**: Batch processing can be implemented with **minimal architectural changes**. PocketFlow already has production-ready primitives, and pflow's template resolution system naturally supports `${item}` injection via the shared store.

---

## 1. PocketFlow Batch Primitives

### 1.1 BatchNode (Sequential)

**Location**: `pocketflow/__init__.py:78-80`

```python
class BatchNode(Node):
    def _exec(self, items):
        return [super(BatchNode, self)._exec(i) for i in (items or [])]
```

**Execution Flow**:
```
BatchNode._run(shared)
    ├─> prep(shared) → returns list of items
    ├─> _exec(items) → for each item:
    │       └─> Node._exec(item) → retry loop → exec(item) → result
    └─> post(shared, items, [result1, result2, ...])
```

**Key Characteristics**:
- Sequential processing via list comprehension
- Each item gets **independent retry logic**
- `prep()` returns iterable, `exec()` processes one item, `post()` gets all results
- No shared state between items (safe for sequential execution)

### 1.2 AsyncParallelBatchNode (Concurrent)

**Location**: `pocketflow/__init__.py:169-171`

```python
class AsyncParallelBatchNode(AsyncNode, BatchNode):
    async def _exec(self, items):
        return await asyncio.gather(*(super(AsyncParallelBatchNode, self)._exec(i) for i in items))
```

**Execution Flow**:
```
AsyncParallelBatchNode._run_async(shared)
    ├─> prep_async(shared) → returns list of items
    ├─> _exec(items) → asyncio.gather(
    │       ├─> AsyncNode._exec(item1) → async retry → exec_async(item1) ─┐
    │       ├─> AsyncNode._exec(item2) → async retry → exec_async(item2) ─┤ PARALLEL
    │       └─> AsyncNode._exec(item3) → async retry → exec_async(item3) ─┘
    │   )
    └─> post_async(shared, items, [result1, result2, result3])
```

**Key Characteristics**:
- Concurrent processing via `asyncio.gather()`
- Results returned in **same order as input** (gather preserves order)
- Each item gets async retry logic independently
- MRO: `AsyncParallelBatchNode → AsyncNode → BatchNode → Node → BaseNode`

### 1.3 State Isolation Analysis

| Component | Isolated Per Item? | Risk Level |
|-----------|-------------------|------------|
| `self.cur_retry` | ✅ Yes (set fresh per _exec) | 🟢 None |
| `prep_res`, `exec_res` | ✅ Yes (function args) | 🟢 None |
| `shared` store | ❌ No (intentionally shared) | 🟡 Medium |
| Node instance vars | ❌ No (same instance) | 🔴 High in parallel |

**Implication**: Sequential batch is safe. Parallel batch requires per-item isolation strategy.

---

## 2. Wrapper Chain Architecture

### 2.1 Current Wrapper Order

**Location**: `src/pflow/runtime/compiler.py:574-700`

```python
# Exact order from _create_single_node():
node = node_class()                              # 1. Base node
node = TemplateAwareNodeWrapper(node, ...)       # 2. Template resolution (conditional)
node = NamespacedNodeWrapper(node, ...)          # 3. Namespacing (conditional)
node = InstrumentedNodeWrapper(node, ...)        # 4. Instrumentation (ALWAYS)
```

### 2.2 Wrapper Responsibilities

| Wrapper | Purpose | `_run()` Behavior |
|---------|---------|-------------------|
| **TemplateAwareNodeWrapper** | Resolve `${var}` templates | Build context, resolve templates, set params, delegate |
| **NamespacedNodeWrapper** | Isolate node outputs | Wrap shared store in proxy, delegate |
| **InstrumentedNodeWrapper** | Metrics, tracing, caching | Record timing, capture LLM usage, check cache, delegate |

### 2.3 Thread-Safety Concern

**Critical Issue** in `TemplateAwareNodeWrapper._run()` (lines 860-871):
```python
# Temporarily modifies shared state!
original_params = self.inner_node.params
self.inner_node.params = merged_params  # ⚠️ RACE CONDITION if parallel
try:
    result = self.inner_node._run(shared)
finally:
    self.inner_node.params = original_params  # RESTORE
```

**Mitigation**: PocketFlow uses `copy.copy(node)` before execution, so each execution gets a shallow copy. However, for parallel batch within the same node execution, this is still a concern.

### 2.4 BatchNodeWrapper Insertion Point (REQUIRES TESTING)

**⚠️ IMPORTANT**: There's a contradiction between the handover document and initial research about wrapper order. Both positions need testing.

#### Option A: Between Template and Namespace (Handover Recommendation)

```python
# Application order (inner to outer):
node = node_class()                              # 1. Base node
node = TemplateAwareNodeWrapper(node, ...)       # 2. Template resolution
node = BatchNodeWrapper(node, ...)               # 3. BATCH (NEW) ← HERE
node = NamespacedNodeWrapper(node, ...)          # 4. Namespacing
node = InstrumentedNodeWrapper(node, ...)        # 5. Instrumentation
```

**Execution chain**: Instrumented → Namespace → Batch → Template → Actual

**Reasoning**:
1. Each batch item gets its own template resolution (Template is innermost)
2. Batch iteration happens inside namespace context
3. Item injection into shared store is visible to Template
4. Metrics capture batch as single logical unit

#### Option B: Between Namespace and Instrumented (Initial Research)

```python
# Application order (inner to outer):
node = node_class()                              # 1. Base node
node = TemplateAwareNodeWrapper(node, ...)       # 2. Template resolution
node = NamespacedNodeWrapper(node, ...)          # 3. Namespacing
node = BatchNodeWrapper(node, ...)               # 4. BATCH (NEW) ← HERE
node = InstrumentedNodeWrapper(node, ...)        # 5. Instrumentation
```

**Execution chain**: Instrumented → Batch → Namespace → Template → Actual

**Reasoning**:
1. Batch operates before namespacing
2. Per-item execution goes through full Namespace → Template chain
3. Batch can inject item at root shared store level

#### Recommendation

**Test Option A first** (handover position) because:
1. Template resolution needs to see `${item}`
2. If batch injects item into namespaced shared, Template builds context from same store
3. Handover author noted this as hypothesis requiring testing

**Key test case**: Verify `${item}` resolves correctly with each option

---

## 3. Template Resolution System

### 3.1 Resolution Location

**Where it happens**: `TemplateAwareNodeWrapper._run()` at line 716

```python
def _run(self, shared: dict[str, Any]) -> Any:
    if not self.template_params:
        return self.inner_node._run(shared)

    # Build context from shared store + initial_params
    context = self._build_resolution_context(shared)

    # Resolve each template
    for key, template in self.template_params.items():
        resolved_value = self._resolve_template_parameter(key, template, context)
        resolved_params[key] = resolved_value

    # Execute with resolved params
    self.inner_node.set_params({**self.static_params, **resolved_params})
    return self.inner_node._run(shared)
```

### 3.2 Context Building

**Source**: `_build_resolution_context()` at line 501

```python
def _build_resolution_context(self, shared: dict[str, Any]) -> dict[str, Any]:
    context = dict(shared)              # Start with shared store
    context.update(self.initial_params) # Planner params override
    return context
```

**Priority Order** (highest wins):
1. `initial_params` (from planner/CLI)
2. `shared` store (runtime data)

### 3.3 Injecting `${item}` for Batch Processing

**Key Insight**: Simply inject into shared store before each item execution!

```python
# In BatchNodeWrapper, before executing each item:
shared["item"] = current_item
shared["batch_index"] = i
shared["batch_total"] = len(items)

# Template resolution automatically picks these up!
# Users write: ${item.name}, ${batch_index}
```

**No modifications needed to template resolution system.**

### 3.4 Supported Template Patterns

| Pattern | Behavior | Type Preserved? |
|---------|----------|-----------------|
| `${var}` | Simple lookup | ✅ Yes |
| `${node.field}` | Dot path traversal | ✅ Yes |
| `${items[0].name}` | Array + path | ✅ Yes |
| `"Hello ${name}"` | String interpolation | ❌ No (always string) |

### 3.5 Unresolved Template Handling

- **Strict mode** (default): Raises `ValueError` → triggers repair system
- **Permissive mode**: Stores in `shared["__template_errors__"]`, continues

---

## 4. IR Schema Extension

### 4.1 Current Node Schema

**Location**: `src/pflow/core/ir_schema.py:130-147`

```json
{
  "id": "string",       // Required
  "type": "string",     // Required
  "purpose": "string",  // Optional
  "params": {           // Optional
    "type": "object",
    "additionalProperties": true
  }
}
```

**Constraint**: `"additionalProperties": false` on node schema means no extra top-level fields without schema change.

### 4.2 Options for Adding Batch Config

#### Option A: Inside `params` (No Schema Change)
```json
{
  "id": "summarize",
  "type": "llm",
  "params": {
    "prompt": "Summarize: ${item}",
    "batch": {
      "items": "${files}",
      "as": "item",
      "parallel": false
    }
  }
}
```

**Pros**: No schema change, backward compatible
**Cons**: Batch config mixed with business params, less discoverable

#### Option B: Top-Level `batch` Field (Schema Change Required)
```json
{
  "id": "summarize",
  "type": "llm",
  "batch": {
    "items": "${files}",
    "as": "item",
    "parallel": true,
    "max_concurrent": 10
  },
  "params": {
    "prompt": "Summarize: ${item}"
  }
}
```

**Pros**: Clear separation, more discoverable, matches task spec
**Cons**: Requires adding `batch` to schema properties

### 4.3 Recommendation

**Use Option B (top-level)** because:
1. Task specification already uses this format
2. Batch is orchestration config, not business logic
3. More discoverable for users and planner
4. Easy schema change (just add property)

---

## 5. Workflow Execution Model

### 5.1 Current State: Synchronous

**Location**: `src/pflow/execution/executor_service.py:111`

```python
action_result = flow.run(shared_store)  # Synchronous!
```

- Calls `flow.run()`, not `flow.run_async()`
- Single-threaded execution
- No event loop management

### 5.2 Async Support Requirements

To use `AsyncParallelBatchNode`, these changes would be needed:

| Component | Current | Required for Async |
|-----------|---------|-------------------|
| `executor_service.py` | `flow.run()` | `await flow.run_async()` |
| All wrappers | `_run()` only | Add `_run_async()` methods |
| CLI handlers | Sync functions | `asyncio.run()` wrapper |
| MCP handlers | Already async | Just await execution |
| Compiler | Creates `Flow` | Create `AsyncFlow` when needed |

**Effort Estimate**: Significant (~5-7 days of work)

### 5.3 Recommendation for Task 96

**Phase 1**: Implement sequential batch using `BatchNode` pattern
- Works with current sync architecture
- No async changes needed
- Gets 80% of the value

**Phase 2** (future): Add parallel batch
- Use `asyncio.to_thread()` for sync nodes
- Add rate limiting via `asyncio.Semaphore`
- Requires async support work

---

## 6. Namespacing and Shared Store

### 6.1 How Namespacing Works

**Location**: `src/pflow/runtime/namespaced_store.py`

**Write Path**:
```python
# Node writes:
shared["output"] = "data"

# NamespacedSharedStore intercepts:
def __setitem__(self, key, value):
    if key.startswith("__") and key.endswith("__"):
        self._parent[key] = value           # Special key → root
    else:
        self._parent[self._namespace][key] = value  # Regular → namespaced
```

**Result**: `shared["node_id"]["output"] = "data"`

**Read Path** (for templates):
- Template resolution uses **RAW shared store** (not proxy)
- `${other_node.output}` → `context["other_node"]["output"]`

### 6.2 Special Keys (Bypass Namespacing)

| Key | Purpose |
|-----|---------|
| `__execution__` | Checkpoint tracking |
| `__llm_calls__` | LLM usage tracking |
| `__progress_callback__` | Progress callbacks |
| `__warnings__` | Node warnings |
| `__cache_hits__` | Cache hit tracking |
| `__template_errors__` | Template/type errors |

### 6.3 Thread-Safety Analysis

| Operation | Thread-Safe? | Notes |
|-----------|--------------|-------|
| Dict writes | ❌ No | Plain dict, no locking |
| List appends | ❌ No | `__llm_calls__.append()` not atomic |
| Template resolution | ❌ No | `dict(shared)` not atomic |

**Current safety**: Single-threaded execution (no parallelism)

### 6.4 Parallel Batch Strategy

For parallel batch, two options:

**Option A: Per-Item Shared Stores** (Recommended)
```python
results = []
for item in items:
    item_shared = shared.copy()  # Shallow copy
    item_shared["item"] = item
    result = execute_node(item_shared)
    results.append(result)
# Merge results back to main shared store
```

**Option B: Thread-Safe Locking** (Complex)
- Add locks to NamespacedSharedStore
- Potential deadlocks, performance overhead

---

## 7. Metrics and Tracing

### 7.1 Current Metrics Collection

**Location**: `src/pflow/runtime/instrumented_wrapper.py`

- Per-node execution timing
- LLM usage from `shared["__llm_calls__"]`
- **Issue**: Dict keyed by `node_id` means only last execution kept

```python
# Current - OVERWRITES previous executions!
self.workflow_nodes[node_id] = duration_ms
```

### 7.2 Batch Metrics Recommendations

**Approach A: Aggregate Metrics** (Recommended for Phase 1)
```python
# Sum all item durations, report once
metrics_collector.record_node_execution(
    node_id,
    total_duration_ms,
    batch_size=len(items)  # NEW field
)
```

**Approach B: Per-Item Metrics** (For detailed analysis)
```python
# Create synthetic sub-node IDs
for i, item in enumerate(items):
    metrics_collector.record_node_execution(
        f"{node_id}[{i}]",
        item_duration_ms
    )
```

### 7.3 Trace Batch Events

Add batch metadata to trace events:
```python
event["batch_info"] = {
    "items_processed": len(items),
    "items_succeeded": success_count,
    "items_failed": failure_count,
    "per_item_durations": [...]
}
```

### 7.4 LLM Tracking

**Good news**: Already works for batch!
- Each LLM call appends to `__llm_calls__` list
- N batch items with LLM calls → N entries
- Costs aggregated correctly by MetricsCollector

---

## 8. Implementation Strategy

### 8.1 Phase 1: Sequential Batch (MVP)

**Changes Required**:

1. **IR Schema** (`ir_schema.py`):
   - Add `batch` property to node schema
   - Define batch config schema (items, as, error_handling)

2. **Compiler** (`compiler.py`):
   - Detect `batch` config in node IR
   - Create `BatchNodeWrapper` between Namespace and Instrumented

3. **New File** (`batch_wrapper.py`):
   - Sequential iteration over items
   - Inject `${item}` into shared store per iteration
   - Collect results into `${node_id.results}`

4. **Validation** (`workflow_validator.py`):
   - Validate batch.items is a template
   - Validate batch.as is valid identifier

5. **Planner Prompts**:
   - Teach planner to recognize batch patterns
   - Add batch examples to workflow generator

### 8.2 Phase 2: Parallel Batch (Future)

**Additional Changes**:

1. **Async Wrapper Support**:
   - Add `_run_async()` to all wrappers
   - Create `AsyncBatchNodeWrapper`

2. **Execution Layer**:
   - Detect async flows, use `flow.run_async()`
   - Event loop management in CLI

3. **Rate Limiting**:
   - `asyncio.Semaphore` for `max_concurrent`

4. **Thread-Safety**:
   - Per-item shared store copies
   - Or: Thread-safe metrics collection

### 8.3 Files to Modify

| File | Phase 1 Changes |
|------|-----------------|
| `src/pflow/core/ir_schema.py` | Add batch config schema to NODE_SCHEMA |
| `src/pflow/runtime/compiler.py` | Apply BatchNodeWrapper at line ~662 (between Template and Namespace) |
| `src/pflow/runtime/batch_wrapper.py` | **NEW** - BatchNodeWrapper class |
| `src/pflow/core/workflow_validator.py` | Validate batch config (items template, valid alias) |
| `src/pflow/planning/prompts/workflow_generator.md` | Add batch pattern guidance |
| `tests/test_runtime/test_batch_wrapper.py` | **NEW** - Unit tests for wrapper |
| `tests/test_integration/test_batch_workflows.py` | **NEW** - E2E batch workflow tests |

---

## 9. Critical Findings Summary

### ✅ What Works in Our Favor

1. **PocketFlow primitives exist** - No need to build from scratch
2. **Template resolution is injection-friendly** - Just add to shared store
3. **Namespacing provides isolation** - Each batch node has its own namespace
4. **Wrapper chain is extensible** - Clear insertion point
5. **LLM tracking already handles multiple calls** - Works for batch

### ⚠️ What Requires Attention

1. **Schema change needed** for top-level batch config
2. **Wrapper order matters** - Must go between Namespace and Instrumented
3. **Metrics overwrite issue** - Need aggregate approach
4. **Thread-safety for parallel** - Requires per-item stores

### ❌ What's Out of Scope for Phase 1

1. Parallel/async execution
2. Thread-safe shared stores
3. Nested batch (batch within batch)
4. Cross-item communication during batch

---

## 10. Open Questions for Implementation

1. **Error Handling Default**: Should `fail_fast` or `continue` be the default?
   - Recommendation: `fail_fast` (matches current behavior)

2. **Results Structure**: Array only, or include metadata?
   - Recommendation: Include `results`, `count`, `success_count`, `error_count`

3. **Item Alias Default**: What should `as` default to?
   - Recommendation: `"item"` (intuitive, matches spec)

4. **Parallel Default**: Should `parallel` default to `true` or `false`?
   - Recommendation: `false` (safe default, explicit opt-in)

---

## References

### Source Files Examined

- `pocketflow/__init__.py` - BatchNode, AsyncParallelBatchNode
- `src/pflow/runtime/compiler.py` - Node creation, wrapper chain
- `src/pflow/runtime/node_wrapper.py` - Template resolution
- `src/pflow/runtime/namespaced_wrapper.py` - Namespace isolation
- `src/pflow/runtime/namespaced_store.py` - Shared store proxy
- `src/pflow/runtime/instrumented_wrapper.py` - Metrics collection
- `src/pflow/core/ir_schema.py` - IR validation
- `src/pflow/core/metrics.py` - Metrics aggregation
- `src/pflow/runtime/workflow_trace.py` - Trace collection
- `src/pflow/execution/executor_service.py` - Workflow execution

### Task Documentation

- `.taskmaster/tasks/task_96/task-96.md` - Task specification
- `.taskmaster/tasks/task_96/research/pocketflow-batch-capabilities.md` - PocketFlow research
- `.taskmaster/tasks/task_96/starting-context/task-96-handover.md` - Previous agent notes
