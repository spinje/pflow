# Task 39 Synergy Analysis for Task 96 Phase 2

**Date**: 2024-12-23 (Updated after deep verification)
**Purpose**: Critical context for implementing Task 96 Phase 2 (parallel batch processing)
**Status**: Design finalized, ready for implementation

---

## Executive Summary

After deep analysis of Task 39 research, careful evaluation of PocketFlow patterns, and **thorough verification of thread safety**, we've arrived at a clean architectural design:

1. **Inherit from Node, not BatchNode** - cleaner, no MRO tricks needed
2. **Self-contained implementation** - no separate concurrent module needed
3. **Thread-safe retry** - implement our own retry to avoid `self.cur_retry` race condition
4. **Deep copy node chain per thread** - required to avoid TemplateAwareNodeWrapper race condition
5. **Consistent code paths** - same `_exec_single()` for both sequential and parallel
6. **Task 39 follows same pattern** - ~15 lines for ParallelGroupNode (also needs deep copy)

**Key insight**: PocketFlow was designed for single-threaded execution. The wrapper chain (specifically TemplateAwareNodeWrapper) mutates shared state during execution. Rather than refactor the wrapper, we isolate each thread with deep copy - a simple, safe solution with negligible overhead.

---

## Understanding the Two Tasks

### Task 96: Batch Processing (Data Parallelism)
```
files[] → [process(f1), process(f2), process(f3)] → results[]
          └──────── SAME operation ──────────────┘
```

- **Pattern**: Same operation on multiple items
- **IR**: Uses EXISTING DAG format with `batch` config on nodes
- **Phase 1**: Sequential batch ✅ DONE
- **Phase 2**: Parallel batch (what we're implementing)

### Task 39: Task Parallelism (Fan-Out/Fan-In)
```
fetch → [analyze, visualize, summarize] → combine
        └──── DIFFERENT operations ─────┘
```

- **Pattern**: Different operations run concurrently on same data
- **IR**: Proposes NEW pipeline format (major undertaking)
- **Phase 1**: Pipeline format + sequential execution
- **Phase 2**: ParallelGroupNode for concurrent execution

### Task 39's Pipeline Format (Context)

Task 39 proposes replacing the current DAG format with a pipeline format:

**Current DAG format (nodes + edges):**
```json
{
  "nodes": [
    {"id": "fetch", "type": "http", ...},
    {"id": "analyze", "type": "llm", ...},
    {"id": "visualize", "type": "llm", ...}
  ],
  "edges": [
    {"from": "fetch", "to": "analyze"},
    {"from": "fetch", "to": "visualize"},
    {"from": "analyze", "to": "combine"},
    {"from": "visualize", "to": "combine"}
  ]
}
```

**Proposed pipeline format:**
```json
{
  "pipeline": [
    {"id": "fetch", "type": "http", ...},
    {
      "parallel": [
        {"id": "analyze", "type": "llm", ...},
        {"id": "visualize", "type": "llm", ...}
      ]
    },
    {"id": "combine", "type": "llm", ...}
  ]
}
```

**Benefits of pipeline format:**
- 25-45% more token-efficient
- Top-to-bottom execution order (no mental reconstruction)
- Parallel is EXPLICIT (`{"parallel": [...]}`)
- Matches how LLMs narrate workflows

**Key insight**: The IR format change is INDEPENDENT of concurrency. Task 39's main work is the new parser/compiler for pipeline format, not the parallel execution itself.

---

## Why Build Parallel in Task 96 (Not Task 39)

1. **Context is fresh** - We just implemented Phase 1-3. The wrapper chain, error handling, shared store patterns are all understood.

2. **Simpler use case** - Batch parallelism (same op, multiple items) is conceptually simpler than task parallelism (different ops). Building on the simple case first validates patterns.

3. **Task 39 becomes cleaner** - If we build parallel now, Task 39 focuses on pipeline IR format (the big change). ParallelGroupNode becomes ~15 lines.

4. **Immediate validation** - We can test parallel execution with real batch workflows RIGHT NOW.

5. **Research recommends this order** - From Task 39 docs: "Task 96 should ideally be done FIRST (teaches async patterns, lower risk)"

---

## Why NOT Inherit from BatchNode

### The Problem with BatchNode

PocketFlow's `BatchNode._exec()` is simple:
```python
class BatchNode(Node):
    def _exec(self, items):
        return [super(BatchNode, self)._exec(i) for i in (items or [])]
```

The MRO trick `super(BatchNode, self)._exec(item)` calls `Node._exec(item)` which has retry:
```python
class Node(BaseNode):
    def _exec(self, prep_res):
        for self.cur_retry in range(self.max_retries):  # <- INSTANCE STATE!
            try:
                return self.exec(prep_res)
            except Exception as e:
                if self.cur_retry == self.max_retries - 1:
                    return self.exec_fallback(prep_res, e)
                if self.wait > 0:
                    time.sleep(self.wait)
```

**The race condition**: `self.cur_retry` is instance state. In parallel execution:
```
Thread A: self.cur_retry = 2 (last retry)
Thread B: self.cur_retry = 0 (first try)
Thread A checks: if self.cur_retry == max_retries - 1  # WRONG! B overwrote it
```

### The Clean Solution

**Inherit from Node directly** and implement our own retry with local variables:

```python
class PflowBatchNode(Node):  # NOT BatchNode!

    def _exec_single(self, idx: int, item: Any) -> tuple[dict | None, dict | None]:
        """Execute single item with retry. Thread-safe (local retry counter)."""
        for retry in range(self.max_retries):  # Local variable, not self.cur_retry
            try:
                result = self.exec(item)
                error = self._extract_error(result)
                if error:
                    return (result, {"index": idx, "item": item, "error": error})
                return (result, None)
            except Exception as e:
                if retry < self.max_retries - 1 and self.wait > 0:
                    time.sleep(self.wait)
                    continue
                return (None, {"index": idx, "item": item, "error": str(e)})
```

**Benefits**:
- Thread-safe retry (local `retry` variable)
- Same method for both sequential and parallel
- No confusing MRO tricks
- Follows PocketFlow's "simple inheritance" pattern

---

## Critical Discovery: TemplateAwareNodeWrapper Race Condition

### The Problem

During implementation verification, we discovered a **second race condition** beyond `self.cur_retry`. The wrapper chain shares a single instance across all items:

```
PflowBatchNode
  └── inner_node (SHARED across all threads!)
        └── NamespacedNodeWrapper
              └── TemplateAwareNodeWrapper  ← RACE CONDITION HERE
                    └── ActualNode (LLMNode, etc.)
```

In `TemplateAwareNodeWrapper._run()` (node_wrapper.py:860-871):

```python
def _run(self, shared: dict[str, Any]) -> Any:
    ...
    # Line 860-861: RACE CONDITION!
    original_params = self.inner_node.params
    merged_params = {**self.static_params, **resolved_params}
    self.inner_node.params = merged_params  # MUTATES SHARED STATE!

    try:
        result = self.inner_node._run(shared)
        return result
    finally:
        self.inner_node.params = original_params  # RESTORES
```

When two threads execute concurrently:

```
Thread A: original_params = inner_node.params     # Gets correct params
Thread A: inner_node.params = merged_params_A     # Sets "Hello Alice"
Thread B: original_params = inner_node.params     # Gets Alice's params! WRONG!
Thread B: inner_node.params = merged_params_B     # Sets "Hello Bob"
Thread A: inner_node._run(shared_A)               # EXECUTES WITH "Bob"! WRONG!
```

### Solutions Considered

We evaluated three approaches:

#### Option A: Refactor TemplateAwareNodeWrapper to Inject into Shared Store

Instead of mutating `inner_node.params`, inject resolved params into shared:

```python
# Instead of:
self.inner_node.params = merged_params

# Do:
for key, value in resolved_params.items():
    shared[key] = value  # Nodes read from shared first via fallback pattern
```

**Pros**: Thread-safe by design, ~30 lines changed
**Cons**: Only works if ALL params use the fallback pattern. We found that some params (like `temperature`) read ONLY from `self.params`:

```python
# LLMNode - uses fallback ✓
prompt = shared.get("prompt") or self.params.get("prompt")

# LLMNode - does NOT use fallback ✗
temperature = self.params.get("temperature", 1.0)
```

If someone wrote `temperature: "${config.temp}"`, the resolved value would NOT reach the node. **This is an edge case but a real risk.**

#### Option B: Use Threading Lock

```python
self._template_lock = threading.Lock()

def _run(self, shared):
    with self._template_lock:
        # ... mutation and execution ...
```

**Pros**: Simple, guaranteed safe
**Cons**: Serializes all template resolution, defeats the purpose of parallelism

#### Option C: Deep Copy Node Chain Per Thread (CHOSEN)

```python
def _exec_parallel(self, items):
    def process_item(idx, item):
        item_shared = dict(self._shared)           # Shallow copy (shares __llm_calls__)
        item_shared[self.item_alias] = item

        thread_node = copy.deepcopy(self.inner_node)  # Each thread gets own copy
        thread_node._run(item_shared)

        return item_shared.get(self.node_id, {})
```

**Pros**:
- No changes to TemplateAwareNodeWrapper or platform nodes
- Works for ALL params (template or static, fallback or not)
- Clean isolation - each thread has its own wrapper chain
- Simple implementation (~5 lines)

**Cons**:
- Memory overhead (evaluated below)
- Performance overhead (evaluated below)

### Performance and Memory Analysis

**What's being copied (per thread)**:
```
NamespacedNodeWrapper      (~50 bytes)
  → TemplateAwareNodeWrapper  (~500-2000 bytes: dicts for params, templates)
    → LLMNode                 (~300 bytes: params dict, retry config)

Total per copy: ~1-3 KB
```

**Performance**:
| Operation | Time |
|-----------|------|
| Deep copy 2KB object | ~50-100 μs |
| LLM API call | 500-5000 ms |
| HTTP request | 50-500 ms |

For 1000 items: 1000 × 100μs = **100 ms total** (0.05% overhead)

**Memory** (with max_concurrent=10):
- Only 10 copies exist at any time (ThreadPoolExecutor reuses workers)
- 10 × 3KB = **30 KB peak memory**
- Each copy is garbage collected after item completes

**Conclusion**: Deep copy overhead is negligible for I/O-bound operations.

### Why Not Nodes with Uncopyable Resources?

Concern: What if a node holds a database connection or file handle?

**Answer**: pflow nodes are stateless by design. They create connections in `exec()` and close them after:

```python
# GOOD: Connection created per execution (pflow pattern)
class GoodNode(Node):
    def exec(self, prep_res):
        with connect_to_database() as conn:  # Created fresh each time
            return conn.query(...)

# BAD: Would break copy (but pflow nodes don't do this)
class BadNode(Node):
    def __init__(self):
        self.db_connection = connect_to_database()  # Can't copy this!
```

All pflow platform nodes (LLM, HTTP, Shell, File) follow the stateless pattern.

### What About __llm_calls__ Tracking?

The shared store is shallow-copied, not deep-copied:

```python
item_shared = dict(self._shared)  # Shallow copy
```

This means `item_shared["__llm_calls__"]` points to the SAME list as `self._shared["__llm_calls__"]`. All items append to the same list. **LLM tracking still works correctly.**

---

## The Final Design

### Architecture

```
PflowBatchNode(Node)  # Inherit from Node, not BatchNode
├── prep(shared) -> list         # Resolve items template
├── exec(item) -> dict           # Process single item (isolated context)
├── _exec_single(idx, item)      # Single item with retry (thread-safe)
├── _exec(items) -> list         # Dispatch to sequential or parallel
├── _exec_sequential(items)      # Loop + _exec_single
├── _exec_parallel(items)        # ThreadPoolExecutor + _exec_single
└── post(shared, prep_res, exec_res)  # Aggregate results
```

### No Separate Concurrent Module

The parallel execution is ~35 lines, self-contained in `batch_node.py`:

```python
def _exec_parallel(self, items: list) -> list:
    """Parallel execution with ThreadPoolExecutor."""
    import copy
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = [None] * len(items)

    def process_item(idx: int, item: Any) -> tuple[int, dict | None, dict | None]:
        # Create isolated shared store for this item
        item_shared = dict(self._shared)
        item_shared[self.node_id] = {}
        item_shared[self.item_alias] = item

        # CRITICAL: Deep copy node chain to avoid TemplateAwareNodeWrapper race condition
        thread_node = copy.deepcopy(self.inner_node)

        # Execute with thread-safe retry
        result, error = self._exec_single_with_node(idx, item, item_shared, thread_node)
        return (idx, result, error)

    with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
        futures = {
            executor.submit(process_item, i, item): i
            for i, item in enumerate(items)
        }
        for future in as_completed(futures):
            idx, result, error = future.result()
            results[idx] = result
            if error:
                self._errors.append(error)
                if self.error_handling == "fail_fast":
                    for f in futures:
                        f.cancel()
                    raise RuntimeError(error["error"])

    return results
```

**Why no shared module?**
- The code is simple (~35 lines)
- Task 39's needs are slightly different (no item context, nodes have own retry)
- Premature abstraction would be over-engineering
- If Task 39 needs shared code, we can extract then
- Both tasks need deep copy for thread isolation (same pattern)

---

## IR Schema Changes

Add parallel execution config to BATCH_CONFIG_SCHEMA:

```python
BATCH_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "string",
            "pattern": r"^\$\{.+\}$",
            "description": "Template reference to array of items",
        },
        "as": {
            "type": "string",
            "pattern": r"^[a-zA-Z_][a-zA-Z0-9_]*$",
            "default": "item",
        },
        "error_handling": {
            "type": "string",
            "enum": ["fail_fast", "continue"],
            "default": "fail_fast",
        },
        # NEW for Phase 2:
        "parallel": {
            "type": "boolean",
            "default": False,
            "description": "Enable concurrent execution of items",
        },
        "max_concurrent": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100,
            "default": 10,
            "description": "Maximum concurrent workers when parallel=true",
        },
        "max_retries": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10,
            "default": 1,
            "description": "Maximum retry attempts per item",
        },
        "retry_wait": {
            "type": "number",
            "minimum": 0,
            "default": 0,
            "description": "Seconds to wait between retries",
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}
```

---

## Thread Safety Analysis

### Two Race Conditions Identified and Solved

| Race Condition | Location | Solution |
|----------------|----------|----------|
| `self.cur_retry` in Node._exec() | PocketFlow's retry loop uses instance state | Local `retry` variable in `_exec_single()` |
| `inner_node.params` mutation | TemplateAwareNodeWrapper._run() mutates shared state | Deep copy node chain per thread |

### What's Safe

| Concern | Status | Notes |
|---------|--------|-------|
| `self._shared` | ✅ Safe | Read-only, set in `prep()` |
| `item_shared = dict(shared)` | ✅ Safe | Each thread creates own SHALLOW copy |
| `__llm_calls__` list | ✅ Safe | Shallow copy shares list, list.append() is GIL-protected |
| Retry counter | ✅ Safe | Local `retry` variable, not `self.cur_retry` |
| Node chain | ✅ Safe | Deep copied per thread, each has own TemplateAwareNodeWrapper |

### What Needs Care

| Concern | Solution |
|---------|----------|
| `self._errors` mutation | Return errors per-thread, merge in main thread |
| Result ordering | Use indexed results array |
| fail_fast cancellation | Cancel remaining futures on first error |
| TemplateAwareNodeWrapper | Deep copy node chain per thread |

### Error Collection Pattern

Instead of mutating shared `self._errors` from threads:

```python
def _exec_single_with_node(self, idx, item, item_shared, thread_node):
    # Returns (result, error_or_none) tuple
    # No shared state mutation
    ...

# In _exec_parallel:
for future in as_completed(futures):
    idx, result, error = future.result()
    if error:
        self._errors.append(error)  # Single-threaded in main, safe
```

### Deep Copy Isolation Pattern

```python
def process_item(idx, item):
    # 1. Shallow copy shared store (shares mutable objects like __llm_calls__)
    item_shared = dict(self._shared)

    # 2. Deep copy node chain (isolates TemplateAwareNodeWrapper.inner_node.params)
    thread_node = copy.deepcopy(self.inner_node)

    # 3. Execute with full isolation
    thread_node._run(item_shared)
```

This pattern ensures:
- Each thread has its own wrapper chain (no params race condition)
- All threads share `__llm_calls__` list (for usage tracking)
- Results are collected safely in main thread

---

## What Task 39 Will Look Like

Task 39's `ParallelGroupNode` follows the same pattern as batch:
- Each node has its own retry logic (in Node._exec)
- No item context needed (nodes use namespacing)
- **ALSO needs deep copy** for the same TemplateAwareNodeWrapper reason

```python
class ParallelGroupNode(Node):
    """Execute child nodes concurrently."""

    def __init__(self, children: list[Node], max_concurrent: int = 10):
        super().__init__()
        self.children = children
        self.max_concurrent = max_concurrent

    def _run(self, shared: dict) -> str:
        import copy
        from concurrent.futures import ThreadPoolExecutor

        def run_child(child):
            # Deep copy to avoid TemplateAwareNodeWrapper race condition
            thread_child = copy.deepcopy(child)
            return thread_child._run(shared)

        with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
            futures = [executor.submit(run_child, child) for child in self.children]
            # Wait for all, let exceptions propagate
            for f in futures:
                f.result()

        return "default"
```

**~20 lines.** Task 39's main work is the pipeline IR format, not the parallel execution.

**Note**: Task 39 can reuse the deep copy pattern we establish here. The TemplateAwareNodeWrapper race condition affects ANY parallel execution of pflow nodes, not just batch.

---

## PocketFlow Class Hierarchy (Reference)

```
BaseNode
├── Node (sync, with retry via self.cur_retry)
│   ├── BatchNode (sequential batch - [super()._exec(i) for i in items])
│   └── Flow (orchestrator)
│       └── BatchFlow (run flow N times with different params)
└── AsyncNode (async, with retry)
    ├── AsyncBatchNode (sequential async batch)
    ├── AsyncParallelBatchNode (concurrent via asyncio.gather)
    └── AsyncFlow (async orchestrator)
        ├── AsyncBatchFlow (sequential async flow runs)
        └── AsyncParallelBatchFlow (concurrent flow runs)
```

**Key insight**: PocketFlow's parallel primitives (`AsyncParallelBatchNode`, `AsyncParallelBatchFlow`) require async nodes with `exec_async()`. Since pflow nodes are sync, we implement parallel ourselves with ThreadPoolExecutor.

---

## Testing Strategy

### Unit Tests for _exec_single (retry logic)

```python
class TestExecSingleRetry:
    def test_success_on_first_try(self):
        """Item succeeds immediately, no retry needed."""

    def test_success_after_retry(self):
        """Item fails once, succeeds on retry."""

    def test_all_retries_exhausted(self):
        """Item fails all retries, error returned."""

    def test_retry_wait_respected(self):
        """Wait time between retries is honored."""

    def test_error_in_result_detected(self):
        """Error in result dict (not exception) is detected."""
```

### Unit Tests for _exec_parallel

```python
class TestExecParallel:
    def test_parallel_execution_basic(self):
        """All items execute and results collected."""

    def test_parallel_preserves_order(self):
        """Results are in same order as input items."""

    def test_parallel_fail_fast_stops(self):
        """First error cancels remaining work."""

    def test_parallel_continue_collects_all(self):
        """All items run even when some fail."""

    def test_max_concurrent_limits_workers(self):
        """Rate limiting respected."""

    def test_parallel_with_retry(self):
        """Retry works correctly in parallel mode."""

    def test_parallel_empty_list(self):
        """Empty input returns empty results."""

    def test_parallel_single_item(self):
        """Single item works (edge case)."""
```

### Thread Safety Tests

```python
class TestThreadSafety:
    def test_isolated_context_per_item(self):
        """Each item gets its own shared store copy."""

    def test_llm_calls_accumulated(self):
        """__llm_calls__ list correctly tracks all calls."""

    def test_errors_collected_safely(self):
        """Errors from multiple threads collected correctly."""

    def test_no_race_on_retry_counter(self):
        """Local retry variable, not self.cur_retry."""
```

### Integration Tests

```python
class TestParallelBatchIntegration:
    def test_batch_with_real_workflow(self):
        """End-to-end: HTTP fetch -> parallel batch process."""

    def test_batch_parallel_vs_sequential_same_results(self):
        """Parallel and sequential produce identical results."""

    def test_batch_with_template_resolution(self):
        """Templates resolve correctly in parallel context."""

    def test_batch_with_namespacing(self):
        """Namespaced outputs work in parallel."""
```

---

## Implementation Plan

### Step 1: Update IR Schema (~10 min)
- Add `parallel`, `max_concurrent`, `max_retries`, `retry_wait` to BATCH_CONFIG_SCHEMA
- Add tests for new schema fields

### Step 2: Refactor PflowBatchNode (~30 min)
- Change inheritance: `class PflowBatchNode(Node)` instead of `BatchNode`
- Add `_exec_single()` with thread-safe retry
- Add `_exec_sequential()` using `_exec_single()`
- Add `_exec_parallel()` with ThreadPoolExecutor
- Update `_exec()` to dispatch based on `self.parallel`
- Update `__init__()` to parse new config fields

### Step 3: Update Existing Tests (~20 min)
- Existing Phase 1 tests should still pass
- May need minor adjustments for new inheritance

### Step 4: Add Phase 2 Tests (~30 min)
- Parallel execution tests
- Retry tests (sequential and parallel)
- Error handling tests (fail_fast, continue)
- Thread safety verification

### Step 5: Integration Testing (~15 min)
- End-to-end test with real workflow
- Verify LLM tracking works in parallel

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Inheritance | `Node` (not `BatchNode`) | Avoid MRO tricks, cleaner design |
| Retry | Own implementation | Thread-safe local variable, not `self.cur_retry` |
| Thread isolation | Deep copy node chain | Avoids TemplateAwareNodeWrapper race condition, no refactoring needed |
| Shared module | No | Simple enough inline (~35 lines), Task 39 follows same pattern |
| Default parallel | `false` | Backward compatible with Phase 1 |
| Default max_concurrent | `10` | Reasonable for LLM APIs with rate limits |
| Default max_retries | `1` | No retry by default (explicit opt-in) |

### Why Deep Copy Over Alternatives

| Alternative | Why Rejected |
|-------------|--------------|
| Refactor TemplateAwareNodeWrapper | Edge case risk: params without fallback pattern (e.g., `temperature`) would break |
| Threading Lock | Serializes execution, defeats purpose of parallelism |
| Thread-local storage | Requires changing all nodes to read from thread-local |

**Deep copy is the safest choice**: ~5 lines of code, no changes to existing components, negligible overhead (0.05% of execution time, 30KB memory).

---

## Comparison: Before vs After

### Before (Phase 1 - BatchNode inheritance)
```python
class PflowBatchNode(BatchNode):
    def _exec(self, items):
        for item in items:
            result = super(BatchNode, self)._exec(item)  # MRO trick
            ...
```
- Confusing `super(BatchNode, self)` call
- Can't safely parallelize (self.cur_retry race)
- Different code paths for sequential vs parallel

### After (Phase 2 - Node inheritance)
```python
class PflowBatchNode(Node):
    def _exec_single(self, idx, item):
        for retry in range(self.max_retries):  # Local, thread-safe
            result = self.exec(item)
            ...

    def _exec_sequential(self, items):
        return [self._exec_single(i, item) for i, item in enumerate(items)]

    def _exec_parallel(self, items):
        with ThreadPoolExecutor(...) as executor:
            return list(executor.map(lambda x: self._exec_single(*x), enumerate(items)))
```
- Clear, no MRO tricks
- Same `_exec_single()` for both modes
- Thread-safe by design

---

## Summary

**The "beautiful" solution is to not fight PocketFlow's design.**

Instead of using BatchNode's MRO trick and working around thread safety issues, we:
1. Inherit from `Node` directly (avoid `self.cur_retry` race condition)
2. Implement our own clean retry with local variables
3. Deep copy the node chain per thread (avoid TemplateAwareNodeWrapper race condition)
4. Use the same `_exec_single()` for both sequential and parallel
5. Keep everything self-contained in `batch_node.py`

**Two race conditions solved**:
- `self.cur_retry` in PocketFlow's Node → local `retry` variable
- `inner_node.params` mutation in TemplateAwareNodeWrapper → deep copy per thread

**Deep copy overhead is negligible**:
- ~100μs per copy vs ~2000ms per LLM call (0.05%)
- 30KB peak memory with 10 concurrent workers

Task 39 will follow the same pattern: simple ThreadPoolExecutor usage with deep copy, ~20 lines for ParallelGroupNode. The real work in Task 39 is the pipeline IR format.
