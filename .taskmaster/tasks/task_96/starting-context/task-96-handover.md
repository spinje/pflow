# Task 96 Handover Memo: Support Batch Processing in Workflows

**From**: Previous agent (context window closing)
**To**: Implementing agent
**Date**: 2024-12-21

---

## 🚨 The Most Important Thing You Need to Know

**Task 96 was carved out of Task 39 because we discovered two DIFFERENT types of parallelism were being conflated:**

| Type | Task | Effort | Impact | PocketFlow Support |
|------|------|--------|--------|-------------------|
| **Data Parallelism** | 96 (this) | Low | High (10-100x) | ✅ Already exists |
| **Task Parallelism** | 39 | High | Medium (2-5x) | ❌ Must build |

**Your job is the EASY one.** PocketFlow already has production-ready batch primitives. You're just exposing them in pflow's IR schema and wrapping existing nodes to use them.

---

## 🔑 Critical Verified Findings

### 1. The "Parameter Passing Blocker" is FALSE

The original research claimed pflow's modification to `Flow._orch()` would break BatchFlow. **This is wrong.**

**Why it's wrong** (I verified this directly in the code):

```python
# pocketflow/__init__.py:104-105 (the modification)
if params is not None:
    curr.set_params(p)

# pocketflow/__init__.py:119-124 (BatchFlow)
def _run(self, shared):
    for bp in pr:
        self._orch(shared, {**self.params, **bp})  # Always passes non-None params!
```

BatchFlow ALWAYS passes explicit params, so the condition is ALWAYS True. **BatchFlow works correctly.**

### 2. AsyncFlow._orch_async is COMPLETELY UNMODIFIED

This is huge. Look at lines 175-181 in `pocketflow/__init__.py`:

```python
async def _orch_async(self, shared, params=None):
    curr, p, last_action = copy.copy(self.start_node), (params or {**self.params}), None
    while curr:
        curr.set_params(p)  # ALWAYS called - no conditional!
        ...
```

The async path was NEVER modified. All async batch classes (`AsyncParallelBatchNode`, `AsyncParallelBatchFlow`) work exactly as documented.

### 3. Namespacing Already Provides Isolation

pflow has automatic namespacing where each node writes to `shared[node_id][key]`. This means parallel nodes write to DIFFERENT namespaces, significantly reducing shared store conflicts.

---

## 📍 Exact File Locations (Verified)

### PocketFlow Classes (in `pocketflow/__init__.py`)

| Class | Lines | Purpose |
|-------|-------|---------|
| `BatchNode` | 78-80 | Sequential batch processing |
| `AsyncBatchNode` | 164-166 | Sequential async batch |
| `AsyncParallelBatchNode` | 169-171 | **Concurrent batch via asyncio.gather()** |
| `BatchFlow` | 119-124 | Run flow multiple times with different params |
| `AsyncParallelBatchFlow` | 200-204 | Concurrent flow runs |

### pflow Files You'll Need to Modify

| File | Purpose |
|------|---------|
| `src/pflow/core/ir_schema.py` | Add `batch` config to node schema |
| `src/pflow/runtime/compiler.py:577-700` | Node instantiation - add batch wrapper |
| `src/pflow/runtime/node_wrapper.py` | May need batch-aware template resolution |
| `src/pflow/planning/prompts/` | Teach planner when to use batch |

### Key Documentation

| File | Why It Matters |
|------|----------------|
| `.taskmaster/tasks/task_96/research/pocketflow-batch-capabilities.md` | I extracted and verified all BatchNode docs here |
| `pocketflow/docs/core_abstraction/batch.md` | PocketFlow's batch documentation |
| `pocketflow/docs/core_abstraction/parallel.md` | PocketFlow's parallel documentation |
| `pocketflow/cookbook/pocketflow-parallel-batch/` | Working example with real performance data |

---

## 🔧 The Wrapper Chain Challenge

pflow wraps every node in multiple layers. The current order (outermost first):

```
InstrumentedNodeWrapper (metrics, tracing, caching)
    └─> NamespacedNodeWrapper (collision prevention)
        └─> TemplateAwareNodeWrapper (${variable} resolution)
            └─> ActualNode
```

**Where does BatchNodeWrapper fit?**

I believe it should go BEFORE TemplateAwareNodeWrapper but AFTER NamespacedNodeWrapper:

```
InstrumentedNodeWrapper
    └─> NamespacedNodeWrapper
        └─> BatchNodeWrapper (NEW)  ← Iterates over items
            └─> TemplateAwareNodeWrapper  ← Resolves ${item.x} per iteration
                └─> ActualNode
```

**Why?** Because:
1. Each batch item needs its own template resolution context
2. The `${item.x}` syntax needs to work within the batch iteration
3. Namespacing should apply at the batch level, not per-item

**⚠️ WARNING**: This is my hypothesis. Test it carefully. The wrapper interactions are subtle.

---

## 🎯 The Template Resolution Challenge

The tricky part is making `${item.x}` work. Currently, template resolution happens in `TemplateAwareNodeWrapper._run()`:

```python
# node_wrapper.py - simplified
def _run(self, shared):
    context = {**shared, **self.initial_params}
    resolved_params = resolve_templates(self.template_params, context)
    self.inner_node.set_params({**self.static_params, **resolved_params})
    return self.inner_node._run(shared)
```

For batch processing, you need something like:

```python
class BatchNodeWrapper:
    def _run(self, shared):
        items = resolve_template(self.items_template, shared)
        results = []
        for item in items:
            # Inject item into context for this iteration
            item_context = {**shared, self.item_alias: item}
            result = self.inner_node._run(item_context)  # Template wrapper will resolve ${item.x}
            results.append(result)
        shared[self.node_id] = {"results": results}
        return "default"
```

**Key insight**: You pass the item-enhanced context DOWN to the template wrapper, which then resolves `${item.x}` naturally.

---

## 🔄 Async Wrapping for Sync Nodes

pflow nodes are currently sync. To use `AsyncParallelBatchNode`, you need to bridge:

```python
import asyncio

async def run_sync_node_async(node, shared):
    return await asyncio.to_thread(node._run, shared)
```

This runs the sync node in a thread pool, allowing concurrent execution for I/O-bound operations.

**Performance note from PocketFlow cookbook**:
- Parallel batch: 5.4x speedup (1136s → 209s for document translation)
- Best for I/O-bound tasks (API calls, file I/O)
- Limited benefit for CPU-bound (Python GIL)

---

## ⚠️ Gotchas and Warnings

### 1. Rate Limiting is Critical

```python
self.semaphore = asyncio.Semaphore(max_concurrent)

async def exec_async(self, item):
    async with self.semaphore:
        return await self.process(item)
```

Without this, you'll hammer APIs and get rate-limited or banned.

### 2. Error Handling Per-Item

Decide early: `fail_fast` vs `continue`. The IR schema should support both:
```json
{
  "batch": {
    "items": "${files}",
    "error_handling": "continue"  // or "fail_fast"
  }
}
```

### 3. Memory for Large Batches

Sequential batch: O(1) memory per item
Parallel batch: O(n) memory (all items in flight)

Consider adding `batch_size` for chunking large datasets.

### 4. Shared Store Reads During Parallel Writes

Even with namespacing, if parallel items READ from the same shared store location while another is writing, you could get stale data. Namespacing helps (different write locations), but be careful.

---

## ❓ Questions to Investigate During Implementation

1. **Does `asyncio.to_thread()` work correctly with pflow's wrapper chain?**
   - The wrappers use instance variables - thread safety?
   - Does `copy.copy()` in PocketFlow's `_orch()` help?

2. **How does the InstrumentedNodeWrapper's metrics collection work with batch?**
   - Should we collect metrics per-item or per-batch?
   - The trace collector might need updates

3. **What happens if template resolution fails for ONE item in a batch?**
   - Should the whole batch fail?
   - Should we skip that item?

4. **How do we handle the `__llm_calls__` tracking in parallel execution?**
   - Multiple threads writing to same list?
   - Need thread-safe collection?

---

## 📚 Files I Created/Modified (Read These)

| File | What I Did |
|------|------------|
| `.taskmaster/tasks/task_96/task-96.md` | Task specification - READ THIS FIRST |
| `.taskmaster/tasks/task_96/research/pocketflow-batch-capabilities.md` | Verified BatchNode documentation |
| `CLAUDE.md` | Added Task 96 to roadmap (before Task 39) |

---

## 🔗 Relationship to Task 39

Task 96 (this) and Task 39 are **complementary**:

```json
{
  "pipeline": [
    {"id": "fetch", ...},
    {
      "parallel": [                           // Task 39: different ops
        {
          "id": "analyze_all",
          "batch": {                          // Task 96: same op × N items
            "items": "${fetch.files}",
            "parallel": true
          },
          "type": "llm", ...
        },
        {"id": "generate_summary", "type": "llm", ...}
      ]
    }
  ]
}
```

**Do Task 96 first** because:
1. Uses existing PocketFlow code (lower risk)
2. Higher impact (10-100x vs 2-5x speedups)
3. Patterns learned here help with Task 39

---

## 💡 Final Advice

1. **Start with sequential batch** (Phase 1 in the spec) - get the IR and wrapper right
2. **Add parallel execution second** (Phase 2) - use `AsyncParallelBatchNode` pattern
3. **Test with real LLM nodes** - that's where the value is (API call parallelism)
4. **The wrapper chain order is everything** - get this wrong and nothing works

---

## ⏸️ STOP - Do Not Begin Yet

Read the task specification at `.taskmaster/tasks/task_96/task-96.md` and the research at `.taskmaster/tasks/task_96/research/pocketflow-batch-capabilities.md` before starting.

When you're ready, tell the user: **"I've read the handover and task specification. I'm ready to begin implementing Task 96."**
