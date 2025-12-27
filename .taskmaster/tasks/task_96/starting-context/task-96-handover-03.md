# Task 96 Handover: Pre-Implementation Verification Complete

**From**: Verification & Planning Agent
**To**: Implementation Agent
**Date**: 2024-12-23
**Context**: All assumptions verified via 7 parallel codebase searches; implementation plan updated to v1.1

---

## The Single Most Important Thing

**The spec's "Error:" prefix detection is misleading.** When the spec says "item returns Error:...", it actually means the result dict has an `error` key with a truthy value. Your `exec()` method returns a dict (the node's namespace contents), NOT a string. The implementation plan v1.1 has been updated to reflect this.

---

## Verified Code Paths (Trust These)

I ran 7 parallel searches and verified every critical assumption. Here are the exact locations:

| What | File:Lines | Verified Behavior |
|------|------------|-------------------|
| Wrapper application | `compiler.py:658-687` | Order: Base → Template → Namespace → Instrumented |
| Batch insertion point | `compiler.py:669-671` | After Namespace, before Instrumented |
| Template context building | `node_wrapper.py:501-523` | `context = dict(shared)` then updates with initial_params |
| NamespacedSharedStore.__setitem__ | `namespaced_store.py:43-55` | Regular keys → `shared[namespace][key]` |
| NamespacedSharedStore.keys() | `namespaced_store.py:132-144` | Returns namespace keys UNION root keys |
| PocketFlow BatchNode | `pocketflow/__init__.py:78-80` | Simple 3-line class, iterates with list comprehension |
| Node._exec retry logic | `pocketflow/__init__.py:67-76` | Retry loop with exec_fallback on final failure |
| Node schema location | `ir_schema.py:130-147` | Inline within FLOW_IR_SCHEMA, uses additionalProperties: false |

---

## The Wrapper Chain Confusion (Resolved)

The earlier handover documents contradicted each other:
- **handover-01** suggested Batch between Template and Namespace
- **handover-02** corrected this: Batch must be OUTSIDE Namespace

**The correct answer**: Batch goes between Namespace and Instrumented.

**Why it matters**: If Batch is inside Namespace, then `shared["item"] = x` writes to `shared["batch_node"]["item"]`, not `shared["item"]`. Template resolution would need `${batch_node.item}` instead of `${item}`. Wrong and ugly.

**Execution chain (correct)**:
```
Instrumented._run(shared)
    → PflowBatchNode._run(shared)
        → for each item:
            → inner_node._run(item_shared)  # item_shared is plain dict
                → NamespacedNodeWrapper._run(item_shared)
                    → creates NamespacedSharedStore(item_shared, node_id)
                    → TemplateAwareNodeWrapper._run(namespaced_proxy)
                        → ActualNode._run(namespaced_proxy)
```

---

## The MRO Trick for Retry Logic

This line in `_exec` is subtle:
```python
result = super(BatchNode, self)._exec(item)
```

Inside `PflowBatchNode`, `super(BatchNode, self)` skips BatchNode in the MRO and goes directly to `Node._exec(item)`. This gives us per-item retry logic for free!

**MRO**: `PflowBatchNode → BatchNode → Node → BaseNode → object`

If you accidentally write `super()._exec(item)` (without the class argument), it would call `BatchNode._exec`, which would try to iterate over the single item as if it were a list. Wrong.

---

## What exec() Actually Returns

Your `exec()` method returns `item_shared.get(self.node_id, {})` - a **dict** containing everything the node wrote to its namespace.

Example return values:
- LLM node: `{"response": "...", "llm_usage": {...}}`
- File read: `{"content": "...", "file_path": "..."}`
- On error: `{"error": "Error: Could not read file...", "content": ""}`

**Never a string.** The spec's "Error:" prefix language is about the VALUE of the error key, not the return type.

---

## Shallow Copy: What's Shared, What's Isolated

`item_shared = dict(self._shared)` creates a shallow copy:

| Object Type | Behavior | Example |
|-------------|----------|---------|
| Immutable (str, int, tuple) | Isolated | Each item gets own copy |
| Mutable (list, dict) | **SHARED** | `__llm_calls__` list is same object |
| New keys | Isolated | `item_shared["item"]` doesn't affect original |

**This is intentional!** LLM tracking works because all items append to the SAME `__llm_calls__` list.

**Potential footgun**: If upstream node output is a mutable object and you modify it, you affect all items. Don't do this.

---

## Output Keys Are Inconsistent Across Nodes

Different node types use different output keys:
- LLM: `response`
- File read: `content`
- MCP: `result`
- Shell: `stdout`
- HTTP: `response`

**Solution**: Capture the entire namespace dict as the result. Don't assume a specific key exists.

---

## Error Detection: Two Layers

The implementation plan v1.1 handles errors in two ways:

1. **Exceptions**: Caught in `_exec` try/except, result set to `None`
2. **Error in result dict**: `_extract_error()` checks `result.get("error")`

**Watch out**: Some nodes use `{"status": "error", "error": "..."}` pattern (LLM, MCP). The current `_extract_error()` only checks for truthy `error` key, which should catch these. But if you see issues, this is where to look.

---

## NamespacedNodeWrapper Works With Plain Dicts

I was worried about this, but it's verified: when you pass a plain `dict` to `inner_node._run()`, the `NamespacedNodeWrapper` inside the chain correctly creates a `NamespacedSharedStore` proxy around YOUR dict.

```python
# This works:
item_shared = dict(self._shared)
item_shared["item"] = current_item
self.inner_node._run(item_shared)  # NamespacedNodeWrapper handles it
# After execution: item_shared[node_id] contains the results
```

---

## Files You'll Touch

| File | Lines | What to Do |
|------|-------|------------|
| `src/pflow/core/ir_schema.py` | ~130-147 | Add `batch` property to inline node schema |
| `src/pflow/runtime/batch_node.py` | NEW | Copy from implementation plan v1.1 |
| `src/pflow/runtime/compiler.py` | ~669-671 | Insert batch wrapper between Namespace and Instrumented |
| `src/pflow/core/workflow_validator.py` | TBD | Add batch config validation |

---

## Questions to Investigate During Implementation

1. **Does TemplateResolver.resolve_value() handle the exact format we need?** The implementation plan shows `var_path = self.items_template.strip()[2:-1]` to extract "x" from "${x}". Verify this works for nested paths like "${node.items}".

2. **What happens if inner_node._run() returns "error" action?** We ignore the return value, but should we check it? Probably not - errors are communicated via exceptions and shared store.

3. **Thread safety of _errors list?** For sequential batch, this is fine. But if Phase 2 adds parallel execution, this list would need synchronization.

---

## What Would Break If I'm Wrong

| If This Is Wrong... | Then This Breaks... |
|---------------------|---------------------|
| NamespacedNodeWrapper creates proxy correctly with plain dict | Entire isolated context approach fails |
| super(BatchNode, self)._exec calls Node._exec | We lose per-item retry logic |
| Template resolution sees root-level keys | `${item}` won't resolve |
| Shallow copy shares mutable objects | `__llm_calls__` tracking breaks |

---

## Files Already Read (Don't Re-Read)

These are already internalized:
- `.taskmaster/tasks/task_96/task-96.md` - Main spec
- `.taskmaster/tasks/task_96/starting-context/task-96-spec.md` - Feature spec v1.2.0
- `.taskmaster/tasks/task_96/implementation/implementation-plan.md` - v1.1 with alterations
- All handover docs (01, 02)
- Research findings

---

## Do NOT Begin Yet

Read this handover and the implementation plan v1.1. When ready, say:

**"I've read the handover and implementation plan. I'm ready to begin implementing Task 96."**

Then wait for the user to give you the go-ahead.
