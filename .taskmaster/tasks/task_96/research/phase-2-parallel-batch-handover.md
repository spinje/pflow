# Phase 2: Parallel Batch Processing - Handover Document

**Date**: 2024-12-23
**Status**: Research/Planning (Phase 1 Complete, Phase 2 Not Started)
**Context Window Note**: This document was created because the implementing agent's context was running out. It captures findings, uncertainties, and next steps.

---

## What Was Implemented (Phase 1) - VERIFIED

Phase 1 implemented **sequential** batch processing. Key files:

| File | Purpose |
|------|---------|
| `src/pflow/runtime/batch_node.py` | PflowBatchNode class |
| `src/pflow/core/ir_schema.py` | BATCH_CONFIG_SCHEMA |
| `src/pflow/runtime/compiler.py` | Wrapper chain integration (lines 671-689) |
| `tests/test_runtime/test_batch_node.py` | 30 unit tests |
| `tests/test_runtime/test_compiler_batch.py` | 15 integration tests |
| `tests/test_core/test_ir_schema.py::TestBatchConfig` | 11 schema tests |

**Total: 56 tests, all passing.**

### Current IR Syntax (Phase 1)

```json
{
  "batch": {
    "items": "${upstream_node.array}",
    "as": "item",
    "error_handling": "fail_fast"
  }
}
```

**NOT implemented**: `parallel`, `max_concurrent` - these were explicitly excluded from Phase 1.

### Key Implementation Details (VERIFIED through testing)

1. **Wrapper chain order is CRITICAL**:
   ```
   Instrumented → PflowBatchNode → Namespace → Template → Actual
   ```
   Batch must be OUTSIDE namespace so `shared["item"] = x` writes to root level.

2. **set_params() must forward to inner_node** - otherwise TemplateAwareNodeWrapper never receives template params.

3. **Shallow copy intentionally shares mutable objects** - `dict(shared)` shares `__llm_calls__` list across items.

4. **Execution is SEQUENTIAL** - items processed one-by-one in a loop.

---

## What Phase 2 Would Add

### Proposed IR Syntax Extension

```json
{
  "batch": {
    "items": "${upstream_node.array}",
    "as": "item",
    "error_handling": "fail_fast",
    "parallel": true,
    "max_concurrent": 10
  }
}
```

### The Goal

Process multiple items CONCURRENTLY instead of sequentially:

```
SEQUENTIAL (Phase 1 - current):
item1 → process → done → item2 → process → done → item3 → process → done

PARALLEL (Phase 2 - proposed):
item1 → process ─┐
item2 → process ─┼→ all done (faster!)
item3 → process ─┘
```

---

## PocketFlow's Existing Parallel Support - VERIFIED BY READING CODE

From `pocketflow/__init__.py`:

```python
# Lines 78-80: Sequential batch (what we inherit from)
class BatchNode(Node):
    def _exec(self, items):
        return [super(BatchNode, self)._exec(i) for i in (items or [])]

# Lines 169-171: Parallel batch (async, uses asyncio.gather)
class AsyncParallelBatchNode(AsyncNode):
    async def _exec(self, items):
        return await asyncio.gather(*[super(AsyncParallelBatchNode, self)._exec(i) for i in (items or [])])
```

**Key observation**: `AsyncParallelBatchNode` requires async nodes. pflow nodes are SYNC.

---

## Implementation Options - NEEDS INVESTIGATION

### Option 1: ThreadPoolExecutor (sync approach)

```python
from concurrent.futures import ThreadPoolExecutor

class PflowParallelBatchNode(BatchNode):
    def _exec(self, items):
        with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
            futures = [executor.submit(self._process_item, item) for item in items]
            return [f.result() for f in futures]
```

**Pros**: No async required, simpler mental model
**Cons**: Thread overhead, GIL limits CPU-bound parallelism (but LLM calls are I/O-bound)

### Option 2: asyncio.to_thread (hybrid approach)

```python
import asyncio

class PflowParallelBatchNode(BatchNode):
    def _exec(self, items):
        async def run_parallel():
            tasks = [asyncio.to_thread(self._process_item, item) for item in items]
            return await asyncio.gather(*tasks)
        return asyncio.run(run_parallel())
```

**Pros**: Uses asyncio patterns, easier to add rate limiting with Semaphore
**Cons**: Mixing sync/async, `asyncio.run()` creates new event loop each time

### Option 3: Inherit from AsyncParallelBatchNode

Would require making pflow nodes async-compatible. Major change.

**Status**: NOT RECOMMENDED for Phase 2 - too invasive.

---

## Critical Questions - MUST INVESTIGATE

### 1. Thread Safety of Shallow Copy Pattern

**Current pattern** (Phase 1):
```python
item_shared = dict(shared)  # Shallow copy
item_shared["item"] = current_item
self.inner_node._run(item_shared)
```

**Question**: Does this work with concurrent threads?

**Hypothesis**: Should work because:
- Each thread gets its OWN `item_shared` dict
- Writes go to thread-local dict (isolated)
- Reads from shared mutable objects (like `__llm_calls__`) might race

**MUST VERIFY**: Is `list.append()` thread-safe in CPython? (I believe yes due to GIL, but verify)

### 2. Error Handling with Concurrency

**Current behavior** (Phase 1):
- `fail_fast`: Raises on first error, stops iteration
- `continue`: Catches errors, continues, aggregates

**Question**: How does `fail_fast` work with threads?

**Options to investigate**:
- `concurrent.futures.wait(return_when=FIRST_EXCEPTION)` - waits until first fails
- Cancel pending futures when one fails?
- Let all complete, then raise first error?

**MUST DECIDE**: What does "fail_fast" mean in concurrent context?

### 3. Rate Limiting Implementation

**Proposed**: `max_concurrent: 10` limits parallel threads.

**With ThreadPoolExecutor**: Set `max_workers=max_concurrent` - straightforward.

**With asyncio**: Use `asyncio.Semaphore(max_concurrent)` - also straightforward.

**Question**: What's the default for `max_concurrent`?
- Unlimited? (dangerous for LLM rate limits)
- 10? (arbitrary but safe)
- Number of items? (effectively unlimited for small batches)

**MUST DECIDE**: Default value and rationale.

### 4. Interaction with InstrumentedNodeWrapper

**Current flow**: Instrumented wraps Batch, captures metrics for the BATCH node.

**Question**: With parallel execution, how do we track:
- Per-item timing?
- LLM calls per item vs total?
- Progress callbacks?

**NEEDS INVESTIGATION**: Read InstrumentedNodeWrapper to understand impact.

---

## Relationship to Task 39 - VERIFIED BY READING TASK SPEC

**Task 39** is about **task parallelism** (different nodes concurrently):
```
fetch → [analyze, visualize, summarize] → combine
        └──── DIFFERENT operations ─────┘
```

**Task 96 Phase 2** is about **data parallelism** (same node, different items):
```
files[] → [process(f1), process(f2), process(f3)] → results[]
          └──────── SAME operation ──────────────┘
```

### Key Insight: Same Concurrency Infrastructure

Both tasks would use the same threading/async patterns:
- ThreadPoolExecutor or asyncio.to_thread
- Error handling (fail_fast/continue)
- Rate limiting (max_concurrent)

**Implication**: Implementing Phase 2 first establishes patterns Task 39 can reuse.

### From Task 39 Spec (verified):

```python
# Task 39's proposed ParallelGroupNode
class ParallelGroupNode(Node):
    def __init__(self, child_nodes):
        self.children = child_nodes

    def _run(self, shared):
        with ThreadPoolExecutor() as executor:
            futures = [executor.submit(child._run, shared) for child in self.children]
            results = [f.result() for f in futures]
        return "default"
```

This is nearly identical to what Phase 2 batch would need!

---

## Proposed Implementation Plan

### Step 1: Schema Extension (Easy)

Add to `BATCH_CONFIG_SCHEMA`:
```python
"parallel": {
    "type": "boolean",
    "default": False,
    "description": "Process items concurrently"
},
"max_concurrent": {
    "type": "integer",
    "minimum": 1,
    "default": 10,
    "description": "Maximum concurrent items (only when parallel=true)"
}
```

### Step 2: Parallel Batch Implementation (Medium)

Create new class or add branch in existing:

```python
class PflowBatchNode(BatchNode):
    def _exec(self, items):
        if self.parallel:
            return self._exec_parallel(items)
        else:
            return self._exec_sequential(items)  # Current implementation

    def _exec_parallel(self, items):
        # ThreadPoolExecutor approach
        with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
            futures = [executor.submit(self._process_single, item) for item in items]
            # Handle errors based on self.error_handling
            return self._collect_results(futures)
```

### Step 3: Compiler Update (Easy)

Pass `parallel` and `max_concurrent` from batch_config to PflowBatchNode.

### Step 4: Testing (Medium)

- Test concurrent execution actually happens (timing-based tests)
- Test thread safety (no race conditions)
- Test error handling modes with concurrency
- Test rate limiting works

---

## Files to Read Before Implementing

1. **`pocketflow/__init__.py`** (lines 78-80, 169-171) - BatchNode and AsyncParallelBatchNode
2. **`src/pflow/runtime/batch_node.py`** - Current Phase 1 implementation
3. **`src/pflow/runtime/instrumented_wrapper.py`** - Understand metrics/tracing interaction
4. **`src/pflow/runtime/namespaced_store.py`** - Verify thread safety of store operations
5. **`.taskmaster/tasks/task_39/task-39.md`** - Understand relationship to task parallelism

---

## Open Questions for Next Agent

1. **ThreadPoolExecutor vs asyncio.to_thread** - Which is better for pflow's use case?

2. **Should we extract a shared concurrency module?** - Code reuse between Task 96 Phase 2 and Task 39?

3. **What's the priority?** - Phase 2 first (simpler, establishes patterns) or Task 39 first (more impactful)?

4. **Default max_concurrent value?** - 10? Unlimited? Configurable globally?

5. **Error handling semantics** - What exactly does fail_fast mean with threads?

---

## Summary

| Aspect | Status |
|--------|--------|
| Phase 1 (sequential batch) | ✅ Complete, 56 tests passing |
| Phase 2 schema | Designed, not implemented |
| Phase 2 execution | Options identified, not decided |
| Thread safety | Hypothesis formed, needs verification |
| Task 39 relationship | Understood, patterns will overlap |

**Next step**: Decide on implementation approach (ThreadPoolExecutor vs asyncio), verify thread safety assumptions, then implement.
