# Task 96 Review: Support Batch Processing in Workflows

## Metadata

- **Implementation Date**: 2024-12-23 to 2024-12-27
- **Branch**: `feat/batch-processing`
- **Total Tests Added**: 140 batch-related tests
- **Files Changed**: 12 files (6 core, 6 test)

## Executive Summary

Task 96 implemented both sequential and parallel batch processing for pflow workflows, enabling a single node to process multiple items from an array with isolated execution contexts. The implementation required significant architectural discoveries—most critically, changing from `BatchNode` to `Node` inheritance to avoid thread-safety issues, and establishing the deep copy pattern for thread isolation that Task 39 will reuse.

## Implementation Overview

### What Was Built

1. **Sequential Batch Processing (Phase 1)**: Process items one at a time with isolated `dict(shared)` context per item
2. **Parallel Batch Processing (Phase 2)**: Concurrent execution using `ThreadPoolExecutor` with deep-copied node chains per thread
3. **Batch Metadata**: Rich timing stats and execution mode info that auto-flows into workflow traces
4. **Batch Error Display**: CLI and MCP display enhancements showing "8/10 items succeeded, 2 failed" summaries

### Deviations from Original Spec

| Spec Said | Actually Built | Reason |
|-----------|---------------|--------|
| Inherit from `BatchNode` | Inherit from `Node` directly | `BatchNode` uses `self.cur_retry` which races in parallel |
| Use MRO trick for retry | Local `retry` variable | Thread-safe, clearer code |
| Phase 2 "later" | Implemented in same PR | Synergy with Task 39, context was fresh |

### Implementation Approach

The wrapper chain position was the critical architectural decision. Batch wraps OUTSIDE namespace:

```
Instrumented._run(shared)
  → PflowBatchNode._run(shared)           # Injects ${item} at ROOT level
    → NamespacedNodeWrapper._run(shared)  # Creates proxy
      → TemplateAwareNodeWrapper._run(proxy)  # Resolves ${item}
        → ActualNode._run(proxy)
```

If batch were inside namespace, `shared["item"] = x` would write to `shared["node_id"]["item"]`, and template resolution for `${item}` would fail.

## Files Modified/Created

### Core Changes

| File | Purpose |
|------|---------|
| `src/pflow/core/ir_schema.py` | Added `BATCH_CONFIG_SCHEMA` with 7 fields: `items`, `as`, `error_handling`, `parallel`, `max_concurrent`, `max_retries`, `retry_wait` |
| `src/pflow/runtime/batch_node.py` | **NEW** - 500+ line `PflowBatchNode` class with sequential and parallel execution |
| `src/pflow/runtime/compiler.py` | Integrated batch wrapper at line ~680, between Namespace and Instrumented |
| `src/pflow/execution/execution_state.py` | Added batch detection via `batch_metadata` key |
| `src/pflow/execution/formatters/success_formatter.py` | Added `_format_batch_node_line()` and `_format_batch_errors_section()` |
| `src/pflow/cli/main.py` | Updated `_format_node_status_line()` and added `_display_batch_errors()` |

### Test Files

| File | Tests | Critical Tests |
|------|-------|----------------|
| `tests/test_core/test_ir_schema.py` | 26 | `test_batch_config_items_not_template` - validates template pattern |
| `tests/test_runtime/test_batch_node.py` | 83 | `test_parallel_retry_resets_namespace` - regression test for namespace reset bug |
| `tests/test_runtime/test_compiler_batch.py` | 15 | `test_batch_node_in_wrapper_chain` - validates wrapper order |
| `tests/test_execution/formatters/test_success_formatter.py` | 23 | `test_batch_errors_capped_at_5` - prevents overwhelming output |

## Integration Points & Dependencies

### Incoming Dependencies

| Component | Depends On | Via |
|-----------|-----------|-----|
| Workflow Compiler | `PflowBatchNode` | `compile_ir_to_flow()` creates batch wrapper when `batch` config present |
| Trace System | Batch output | `batch_metadata` key captured in `shared_after` |
| CLI Display | Batch step fields | `is_batch`, `batch_total`, `batch_failed` in execution steps |
| MCP Display | Batch step fields | Same fields via `format_success_as_text()` |

### Outgoing Dependencies

| This Task | Depends On | Via |
|-----------|-----------|-----|
| Template Resolution | `TemplateResolver.resolve_value()` | Resolves `${node.items}` to actual array |
| Namespace Store | `NamespacedSharedStore.keys()` | Returns union of namespace + root keys (critical for `${item}` visibility) |
| Instrumented Wrapper | `InstrumentedNodeWrapper` | Wraps batch for metrics/tracing |

### Shared Store Keys

| Key Pattern | Purpose | Data Structure |
|-------------|---------|----------------|
| `shared[node_id].results` | Array of per-item results | `list[dict]` |
| `shared[node_id].batch_metadata` | Execution metadata | `{"parallel": bool, "timing": {...}, ...}` |
| `shared[node_id].errors` | Error details | `list[{"index": int, "item": Any, "error": str}]` or `None` |
| `shared[item_alias]` | Current item during iteration | `Any` (injected at root level) |

## Architectural Decisions & Tradeoffs

### Key Decisions

| Decision | Reasoning | Alternative Rejected |
|----------|-----------|---------------------|
| Inherit from `Node` not `BatchNode` | `BatchNode` uses `self.cur_retry` instance state that races in parallel | MRO trick was clever but obscure and not thread-safe |
| Deep copy node chain per thread | `TemplateAwareNodeWrapper` mutates `inner_node.params`—races without isolation | Threading lock would serialize execution, defeating parallelism |
| Shallow copy shared store | `__llm_calls__` list needs to accumulate across all items (GIL-protected) | Deep copy would isolate tracking, breaking metrics |
| Batch outside namespace wrapper | Item alias must be at root level for `${item}` to resolve | Inside would write to `shared["node_id"]["item"]` |
| No shared concurrency module | ~100 lines inline, Task 39 follows same pattern | Premature abstraction; can extract later if needed |

### Technical Debt Incurred

| Debt | Reason | Future Fix |
|------|--------|------------|
| `exec()` raises `NotImplementedError` | Inherited from Node but never called (we override `_exec`) | Document clearly, or restructure inheritance |
| `# noqa: C901` on `_collect_parallel_results` | Concurrent result collection is inherently complex | Accept complexity, document well |

## Testing Implementation

### Test Strategy Applied

1. **Unit tests first**: `PflowBatchNode` in isolation with mock inner nodes
2. **Integration tests**: Through compiler with real node types (ValueNode, ShellNode)
3. **Thread safety tests**: Verify isolation with concurrent execution
4. **Regression tests**: Specific tests for bugs found during review

### Critical Test Cases

| Test | What It Catches |
|------|-----------------|
| `test_parallel_retry_resets_namespace` | Namespace pollution between retries in parallel mode |
| `test_batch_with_template_resolution` | `set_params()` forwarding to inner node chain |
| `test_batch_node_in_wrapper_chain` | Correct wrapper order (Batch outside Namespace) |
| `test_parallel_preserves_order` | Result ordering despite completion order |
| `test_llm_calls_accumulated_correctly` | `__llm_calls__` shared via shallow copy |

## Unexpected Discoveries

### Gotchas Encountered

1. **`set_params()` doesn't forward by default**: `BaseNode.set_params()` only sets `self.params`. Batch must override to forward to inner node, or `TemplateAwareNodeWrapper` never sees templates.

2. **NamespacedSharedStore.keys() returns UNION**: The proxy returns both namespace keys AND root keys. This is WHY `${item}` works—template resolution sees root-level keys through the proxy.

3. **Shell node outputs strings, not arrays**: `${shell.stdout}` is a string like `'["a","b","c"]\n'`. For batch processing, use HTTP node (parses JSON) or other array-producing nodes.

4. **Dual display paths**: CLI has `_display_execution_summary()` in `main.py`, MCP uses `format_success_as_text()` in `success_formatter.py`. BOTH needed updating for batch display.

### Edge Cases Found

| Edge Case | Handling |
|-----------|----------|
| Empty items array | Returns empty results, no errors |
| Single item | Works correctly in both modes |
| `max_concurrent=1` | Effectively sequential (useful for debugging) |
| Item is `0` or `""` (falsy) | Use `if key in shared` not `shared.get(key) or ...` |
| Partial writes before failure | Namespace reset on each retry |

## Patterns Established

### Reusable Patterns

**1. Deep Copy for Thread Isolation**
```python
def process_item(idx, item):
    thread_node = copy.deepcopy(self.inner_node)  # Thread-local copy
    return thread_node._run(item_shared)
```
Task 39's `ParallelGroupNode` will use this exact pattern.

**2. Thread-Safe Retry with Local Variable**
```python
for retry in range(self.max_retries):  # Local, not self.cur_retry
    try:
        result = self._execute(item)
        return result
    except Exception as e:
        if retry < self.max_retries - 1:
            time.sleep(self.retry_wait)
            continue
        raise
```

**3. Shallow Copy for Shared Mutable Tracking**
```python
item_shared = dict(shared)  # Shallow: shares __llm_calls__ list
item_shared[self.node_id] = {}  # Fresh namespace per item
item_shared[self.item_alias] = item  # Inject at root
```

**4. Batch Detection via Metadata Key**
```python
if isinstance(node_output, dict) and "batch_metadata" in node_output:
    # It's a batch node
```

### Anti-Patterns to Avoid

| Anti-Pattern | Why It Fails |
|--------------|--------------|
| `shared.get("item") or shared.get("file")` | Fails when item is `0` or `""` (falsy) |
| Deep copy of shared store | Breaks `__llm_calls__` accumulation |
| Batch inside namespace wrapper | `${item}` won't resolve (wrong level) |
| `self.cur_retry` for parallel retry | Races between threads |

## Breaking Changes

### API/Interface Changes

| Change | Impact |
|--------|--------|
| New `batch` property on nodes | Additive, no breaking change |
| New output keys (`batch_metadata`, etc.) | Additive, existing code ignores |

### Behavioral Changes

| Change | Impact |
|--------|--------|
| Batch nodes show "8/10 items succeeded" | Improved UX, no breaking change |
| Trace files include batch timing | More data in traces, no breaking change |

## Future Considerations

### Extension Points

1. **Task 39 Integration**: `ParallelGroupNode` should use same deep copy pattern, same `max_concurrent` config
2. **Async Batch**: Replace `ThreadPoolExecutor` with `asyncio.gather` + `to_thread()` for async nodes
3. **Nested Batch**: Batch node containing another batch node (not tested, may work)

### Scalability Concerns

| Concern | Mitigation |
|---------|------------|
| Deep copy overhead for large node chains | Measured at ~100μs vs ~2000ms for LLM calls (0.05%) |
| Memory with many concurrent items | `max_concurrent` defaults to 10, caps at 100 |
| Error list size with many failures | Display capped at 5 errors |

## AI Agent Guidance

### Quick Start for Related Tasks

**For Task 39 (Parallel Nodes)**:
1. Read `batch_node.py` lines 420-480 (`_exec_parallel`)
2. Copy the deep copy pattern exactly
3. Your `ParallelGroupNode` is ~20 lines using established patterns

**For any wrapper chain work**:
1. Read `compiler.py` lines 650-700 to understand wrapper order
2. Batch is OUTSIDE namespace—this is critical and non-negotiable

**For template resolution issues**:
1. Check if `set_params()` forwards to inner node
2. Check if item alias is injected at ROOT level (not in namespace)
3. Verify `NamespacedSharedStore.keys()` behavior

### Common Pitfalls

| Pitfall | Solution |
|---------|----------|
| Template returns `None` for `${item}` | Add `set_params()` forwarding to inner node |
| Parallel tests pass locally, fail in CI | Use `dict(shared)` shallow copy, not deep copy |
| Retry counter shared between items | Use local `retry` variable, not `self.cur_retry` |
| Only CLI or only MCP shows batch info | Update BOTH display paths |

### Test-First Recommendations

When modifying batch processing:
1. Run `test_batch_node_in_wrapper_chain` first (validates architecture)
2. Run `test_parallel_retry_resets_namespace` (catches context pollution)
3. Run full batch suite: `pytest tests/test_runtime/test_batch_node.py -v`

When modifying display:
1. Run `test_batch_errors_capped_at_5` (validates truncation)
2. Run `pytest tests/test_execution/formatters/test_success_formatter.py -v`

---

## Appendix: Key Code Locations

| Concept | File | Line Range |
|---------|------|------------|
| Batch schema | `ir_schema.py` | 117-175 |
| Wrapper chain insertion | `compiler.py` | 671-689 |
| Sequential execution | `batch_node.py` | 170-200 |
| Parallel execution | `batch_node.py` | 420-480 |
| Thread-safe retry | `batch_node.py` | 200-260 |
| Batch detection | `execution_state.py` | 85-100 |
| CLI batch display | `main.py` | `_format_node_status_line()` |
| MCP batch display | `success_formatter.py` | `_format_batch_node_line()` |

---

*Generated from implementation context of Task 96*
