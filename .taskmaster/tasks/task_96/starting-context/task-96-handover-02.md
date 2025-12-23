# Task 96 Handover: Batch Processing Implementation

**From**: Research & Spec Agent
**To**: Implementation Agent
**Date**: 2024-12-22
**Context Window**: Exhausted after deep architectural analysis

---

## 🔑 The One Thing You Must Understand

**Batch processing is a map operation.** Each item execution must be independent. This single insight drove every architectural decision. Don't think of it as "running the same node multiple times" - think of it as "independent function applications with collected results."

---

## 🚨 The Critical Discovery That Changed Everything

We originally assumed BatchNodeWrapper could be inserted between TemplateAwareNodeWrapper and NamespacedNodeWrapper. **This was wrong.**

**Why it fails:**
```python
# NamespacedSharedStore.__setitem__ (namespaced_store.py:43-55)
def __setitem__(self, key, value):
    if key.startswith("__") and key.endswith("__"):
        self._parent[key] = value  # Special keys → root
    else:
        self._parent[self._namespace][key] = value  # Regular keys → NAMESPACED!
```

If Batch is inside the namespace context and does `shared["item"] = x`, it writes to `shared["batch_node"]["item"]`, NOT `shared["item"]`. Template resolution would need `${batch_node.item}` instead of `${item}`. Ugly and wrong.

**The fix:** Batch must be OUTSIDE namespace - between NamespacedNodeWrapper and InstrumentedNodeWrapper. This gives Batch access to the raw shared dict.

---

## 🧠 The Decision Journey (Why Option D Won)

We evaluated 4 options. The user pushed back on my initial recommendation and asked me to think without bias. This led to Option D.

| Option | Approach | Why Rejected/Chosen |
|--------|----------|---------------------|
| **A: Clear+Capture** | Clear namespace before each iteration | Hacky. Breaks accumulator patterns. Batch manipulates Namespace's domain. |
| **B: Child Namespaces** | `node[0]`, `node[1]`, etc. | Complex. Requires compiler changes to skip NamespacedNodeWrapper. |
| **C: Special Keys** | Use `__item__` to bypass namespace | User must write `${__item__}` - ugly. Implementation leak. |
| **D: Isolated Copy** | `item_shared = dict(shared)` per item | ✅ Semantically correct. Simple. Parallel-ready. Task 39 compatible. |

**The winning pattern:**
```python
for item in items:
    item_shared = dict(shared)        # Isolated context
    item_shared[self.node_id] = {}    # Clean namespace for this item
    item_shared["item"] = item         # Inject alias at root

    self.inner_node._run(item_shared)  # Execute with isolation

    results.append(item_shared.get(self.node_id, {}))

shared[self.node_id] = {"results": results, ...}  # Write to original
```

---

## 🔍 Verified Code Paths (Trust These)

I ran 8 parallel subagents to verify assumptions. Here's what was confirmed:

| Finding | File:Lines | Implication |
|---------|------------|-------------|
| Wrapper order: Base→Template→Namespace→Instrumented | `compiler.py:658-687` | Batch goes after Namespace |
| Template uses `dict(shared)` for context | `node_wrapper.py:513` | Captures all keys including root |
| NamespacedSharedStore `keys()` returns namespace+root | `namespaced_store.py:132-144` | `${item}` visible if at root |
| `_run()` returns action string, not data | `pocketflow/__init__.py:32-35` | Capture from shared store, not return value |
| Errors use "Error:" prefix convention | Various node implementations | Don't check for None as error |

---

## ⚡ Why This Prepares for Task 39 (Fan-Out)

The user specifically asked about this. The isolated context pattern works for BOTH:

```
Task 96 (Batch - same op × N items):
    shared → [item_shared_1, item_shared_2, ...] → [result_1, result_2, ...] → merge

Task 39 (Fan-out - different ops concurrently):
    shared → [node_A_shared, node_B_shared, ...] → [result_A, result_B, ...] → merge
```

Same pattern. When we add `asyncio.gather()` for parallel batch, no architectural changes needed. When Task 39 comes, same approach applies.

---

## 🎯 Edge Cases That Aren't Obvious

1. **Shallow copy shares mutable objects** - `item_shared["__llm_calls__"]` points to the SAME list as `shared["__llm_calls__"]`. This is GOOD - LLM tracking still works across all items.

2. **Cross-node references work** - If batch params include `${previous_node.output}`, it resolves from the copy because `dict(shared)` captures previous nodes' namespaces.

3. **Multiple batches in workflow** - Each batch has its own `node_id` namespace. Item aliases are temporary and don't collide. Verified this works.

4. **None is valid success** - Don't treat `None` as error. Side-effect nodes and "not found" results legitimately return None. Use "Error:" prefix for error detection.

5. **Entire namespace as result** - Each item's result is the whole namespace dict (`{"response": "...", "llm_usage": {...}}`), not a single value. This avoids the "which key is primary?" problem.

---

## ⚠️ Warnings and Gotchas

1. **Don't use save/restore pattern** - We explicitly chose NOT to save/restore the item alias. Isolated copies mean the original shared is never touched during iteration. Simpler and safer.

2. **Don't clear namespace between iterations** - With isolated copies, each item gets a fresh `item_shared[node_id] = {}`. No need to clear anything.

3. **Wrapper chain confusion** - Wrappers are APPLIED inner-to-outer (in compiler) but EXECUTED outer-to-inner (at runtime). The execution chain is: `Instrumented → Batch → Namespace → Template → Actual`

4. **Template resolution timing** - Template resolution happens INSIDE the inner chain (in TemplateAwareNodeWrapper). By the time it runs, `item_shared["item"]` already exists because Batch injected it.

5. **Capturing output** - After `inner_node._run(item_shared)`, the result is in `item_shared.get(self.node_id, {})`, NOT in the return value (which is just an action string like "default").

---

## 📁 Key Files You'll Touch

| File | What to Do |
|------|------------|
| `src/pflow/core/ir_schema.py` | Add `batch` to NODE_SCHEMA properties |
| `src/pflow/runtime/compiler.py` | Insert BatchNodeWrapper at ~line 670 (after Namespace, before Instrumented) |
| `src/pflow/runtime/batch_wrapper.py` | NEW FILE - the core implementation |
| `src/pflow/core/workflow_validator.py` | Add batch config validation |

---

## 📚 Essential Reading

Before implementing, read these in order:

1. **The spec**: `.taskmaster/tasks/task_96/starting-context/task-96-spec.md` (v1.2.0)
2. **Research findings**: `.taskmaster/tasks/task_96/starting-context/research-findings.md`
3. **NamespacedSharedStore**: `src/pflow/runtime/namespaced_store.py` (understand __setitem__, __getitem__, keys())
4. **Compiler wrapper chain**: `src/pflow/runtime/compiler.py:574-700` (_create_single_node function)
5. **Template resolution**: `src/pflow/runtime/node_wrapper.py:501-523` (_build_resolution_context)

---

## ❓ Questions to Investigate During Implementation

1. **Metrics collection** - InstrumentedNodeWrapper records `node_id → duration`. With batch, we have N executions. Should we aggregate or report per-item? The spec says aggregate, but verify this doesn't break anything.

2. **Trace events** - WorkflowTraceCollector captures per-node execution. Should batch create N trace events or 1 with batch metadata? Consider what's most useful for debugging.

3. **Error in first item with continue mode** - If item 0 fails but we continue, does `results[0] = None` or do we capture whatever partial output exists?

---

## 🛑 STOP - Do Not Begin Yet

Read the spec at `.taskmaster/tasks/task_96/starting-context/task-96-spec.md` thoroughly. It has 19 rules, 13 edge cases, and 29 test criteria that are the source of truth.

When you've read it, say: **"I've read the handover and spec. I'm ready to begin implementing Task 96."**

---

*This handover was written with care. The architectural decisions here were hard-won through systematic verification. Trust the isolated context model - it's semantically correct and future-proof.*
