# Task 108 Review: Smart Trace Debug Output

## Metadata

- Implementation Date: 2026-03-23
- Branch: `feat/smart-trace-debug`
- Phases: 1 (trace enrichment + report), 1.5 (`__llm_calls__` removal), 2 (errors/warnings/costs), D1-D10 (deferred fixes), docs cleanup
- Final test count: 4346 (from 4269 baseline)

## Executive Summary

Redesigned pflow's trace system from a flat, truncated JSON format (1.2.0) to a tree-structured, untruncated format (2.0.0). Built a report generator that converts traces into navigable markdown directories — one file per node with rendered prompts, responses, cost data, error summaries with template fix suggestions, and anomaly warnings. Removed the parallel `__llm_calls__` accumulator, making trace events the single source of truth for LLM cost data.

The scope diverged significantly from the original spec (which envisioned a single "smart debug" markdown file). Through discussion with the user, the vision evolved to a full execution report system — directory of files mirroring workflow structure, designed for git diffing between runs.

## Implementation Overview

### What Was Built

**Trace format 2.0.0:**
- Replaced `shared_before`/`shared_after` (O(n²) full-store snapshots) with focused `node_output`, `template_resolutions`, `node_params`, `mutations`
- Tree-structured events: batch items nested in parent events, sub-workflow events embedded
- All value truncation removed (only key hygiene remains)
- Per-batch-item trace events via shared-list accumulator pattern
- Sub-workflow trace propagation via child `WorkflowTraceCollector` instances
- `template_resolutions` captured from `TemplateAwareNodeWrapper.last_resolutions`
- Trace save moved to `finally` block (survives Ctrl+C)

**Report generator (`--report` flag):**
- Hierarchical markdown directory mirroring workflow structure
- Per-node files: metadata + rendered prompt + response
- Batch items: per-item files in subdirectories
- Sub-workflows: nested directories
- Summary.md at every level with pipeline tables
- Phase 2: Cost columns, error summaries with template fix suggestions, anomaly warnings

**`__llm_calls__` removal (Phase 1.5):**
- Eliminated ~150 lines of parallel cost tracking code
- `WorkflowTraceCollector.collect_llm_calls()` as single source of truth
- Trace collector always created (even with `--no-trace`)

### Deviation from Original Spec

The original Task 108 spec (January 2026) envisioned:
- A single markdown file from `pflow trace debug`
- Rule-based error classification
- Progressive disclosure with drill-down commands
- MCP `get_debug_trace` tool

What was actually built:
- A directory of markdown files from `--report` flag
- Per-node rendered prompts (the #1 agent need, per research)
- Tree-structured trace format (not flat)
- No `shared_before`/`shared_after` (replaced with focused fields)
- Phase 2 smart analysis in summary.md (not a separate command)
- MCP tool deferred to separate task (needs design for multi-file access)

The pivot happened during planning when the user said: "The core problem I think I want to solve is so that you can SEE the results of a workflows internal steps and UNDERSTAND the relationship of an llm nodes input and its output." This aligned with the "Execution Report" vision from the research docs, not the original "Smart Debug" spec.

## Files Modified/Created

### Core Changes

| File | What Changed |
|------|-------------|
| `src/pflow/runtime/workflow_trace.py` | Full rewrite: format 2.0.0, new `record_node_execution()` API, `_sanitize_for_json()` (replaces `_filter_shared()`), `_collect_llm_summary()` with `total_cost_usd`, `collect_llm_calls()` tree walker, `enable_llm_interception` flag, `threading.local()` for `_current_node`, cached event support |
| `src/pflow/runtime/wrappers/instrumented_wrapper.py` | Rewrote `_record_trace()` (focused fields instead of full snapshots), added `_find_template_wrapper()` and `_find_batch_or_workflow_node()` chain traversals, `_enrich_llm_cost()`, cached node trace events, mutations key filtering. Removed `_capture_llm_usage()`, `_find_llm_prompt()`, `_validate_llm_json_output()`, `shared_before` dict copy |
| `src/pflow/runtime/wrappers/batch_node.py` | Added `_capture_item_trace()`, `_find_in_chain()`, `_batch_trace` accumulator init in `prep()`, `_trace_items` transfer in `post()`. Removed `_capture_item_llm_usage()` |
| `src/pflow/runtime/wrappers/template_wrapper.py` | Added `last_resolutions` attribute + `wrapper_attrs` entry. Set `last_resolutions` before each raise in resolution loop (2 error paths) |
| `src/pflow/runtime/workflow_executor.py` | Added `_trace_collector` to `_PROPAGATED_KEYS`, child collector creation in `exec()`, `_child_trace_events` storage. Removed `__llm_calls__` from `_PROPAGATED_KEYS` |
| `src/pflow/execution/executor_service.py` | Auto-creates `WorkflowTraceCollector` when none provided. Always stores `_trace_collector` in shared store. Removed `__llm_calls__` init |
| `src/pflow/core/trace_report.py` | NEW: Report generator (~330 lines). Tree walker, per-node markdown, summaries, cost computation, error/warning sections, template fix suggestions |
| `src/pflow/cli/commands/trace.py` | NEW: `pflow trace report` CLI command with auto-detect latest trace |
| `src/pflow/cli/main.py` | `--report` and `--report-dir` flags, `_save_trace_and_report()` helper, trace save consolidation to `finally` block, `allow_interspersed_args=True` |
| `src/pflow/execution/formatters/success_formatter.py` | Reads from `trace.collect_llm_calls()` instead of `shared["__llm_calls__"]` |
| `src/pflow/execution/formatters/error_formatter.py` | Same migration |
| `src/pflow/cli/workflow_errors.py` | Same migration |

### Test Files

| File | Tests | Notes |
|------|-------|-------|
| `tests/test_core/test_trace_report.py` | 58 | NEW: comprehensive report generator tests (cost, errors, warnings, suggestions, format compat) |
| `tests/test_runtime/test_trace_integration.py` | 9 | NEW: integration tests for fragile seams (wrapper chain, batch, sub-workflows, parallel, errors) |
| `tests/test_runtime/test_workflow_trace.py` | 39 | 18 updated, 3 removed, 8 new (format 2.0.0, `collect_llm_calls`, cost summary) |
| `tests/test_runtime/test_instrumented_wrapper.py` | 33 | 9 updated for new trace API, removed `__llm_calls__` tests |
| `tests/test_runtime/test_batch_node.py` | 136 | 10 updated for `_batch_trace` pattern |

**Critical tests** (catch real integration bugs, not just coverage):
- `test_template_resolutions_flow_through_wrapper_chain_on_error` — validates 5-link delegation chain
- `test_batch_items_appear_in_trace_event` — validates 4-handoff batch trace pipeline
- `test_trace_to_report_format_compatibility` — catches field name drift between trace and report
- `test_llm_accumulation_across_nodes` — guards cost chain (silent $0.00 on break)
- `test_sub_workflow_trace_tree` — validates child collector → parent event embedding

## Integration Points & Dependencies

### Load-Bearing Integration Points

| Integration | Mechanism | What Breaks If Changed |
|-------------|-----------|----------------------|
| Template resolutions → trace | `TemplateAwareNodeWrapper.last_resolutions` read via `_find_template_wrapper()` traversal through `NamespacedNodeWrapper.__getattr__` | Reports lose rendered prompts (silently empty) |
| Batch item traces → parent event | `_batch_trace` shared-list → `_trace_items` instance attr → `_find_batch_or_workflow_node()` class name match | Batch items disappear from traces |
| Sub-workflow traces → parent event | `_trace_collector` propagation → child collector → `_child_trace_events` → chain traversal | Sub-workflow internals invisible |
| Cost tracking | `_enrich_llm_cost()` → `_record_trace()` → `collect_llm_calls()` → `MetricsCollector` | Costs silently become $0.00 |
| Report from trace | `generate_report()` reads JSON fields by exact name | Field rename = empty reports |

### Shared Store Keys

| Key | Purpose | Lifecycle |
|-----|---------|-----------|
| `_trace_collector` | Trace collector reference for sub-workflow propagation | Set by `executor_service`, propagated via `_PROPAGATED_KEYS` |
| `_batch_trace` | Per-batch-item trace accumulator (dict of node_id → list) | Set in `PflowBatchNode.prep()`, consumed in `post()` |

## Architectural Decisions & Tradeoffs

### Key Decisions

**1. Tree trace vs flat trace**
- **Decision**: Tree-structured events (batch items and sub-workflow events nested in parent events)
- **Reasoning**: Execution IS a tree. The trace, report directory, and execution structure should have the same shape. Flat traces push reconstruction complexity to every consumer.
- **Alternative rejected**: Flat events with metadata (depth, workflow_stack) — simpler to produce but harder to consume

**2. Remove `shared_before`/`shared_after`**
- **Decision**: Replace with `node_output` + `template_resolutions` + `node_params` + `mutations`
- **Reasoning**: Full-store snapshots are O(n²) — node N's snapshot contains all outputs from 1..N-1. This was the root cause of needing truncation. Full state is reconstructable from `node_output` sequence.
- **Tradeoff**: Lost `modified` detection in mutations (no value comparison). Acceptable — the report cares about what each node produced.

**3. Keep LLM interception (don't remove)**
- **Decision**: Keep for top-level workflows, skip for child collectors
- **Reasoning**: Captures ground truth (actual API call string). Verified LLM node doesn't modify prompt, so `template_resolutions` is equivalent — but ground truth is a safety net.
- **Alternative rejected**: Remove interception entirely, rely on `template_resolutions` — too risky without safety net

**4. Remove `__llm_calls__` accumulator**
- **Decision**: Single source of truth via trace events
- **Reasoning**: Two parallel data paths (accumulator + trace events) carrying identical data. Removing eliminated ~150 lines and the O(n) `dict(shared)` copy per node.
- **Risk mitigated by**: `test_llm_accumulation_across_nodes` integration test with explicit `assert total_cost_usd > 0`

**5. `last_resolutions` set-before-raise instead of try/finally**
- **Decision**: Set `self.last_resolutions` before each raise in the resolution loop (2 locations)
- **Reasoning**: `try/finally` would require re-indenting ~120 lines of complex loop body. High diff noise, high risk of introducing bugs.
- **Technical debt**: A 3rd raise path added to the loop must remember to set `last_resolutions` first. Comments mark both locations.

### Technical Debt

- `last_resolutions` set-before-raise fragility (see above)
- Two independent cost computation implementations (`_collect_llm_summary` in trace, `_compute_event_cost` in report) — same tree traversal, but could diverge
- `_validate_llm_json_output` was removed (crude heuristic, depended on removed `shared_before`)

## Patterns Established

### Shared-List Accumulator for Parallel Data Flow

When data needs to flow from parallel threads back to a parent:
1. Init a mutable container in `self._shared` before dispatch
2. Each thread gets a shallow copy of shared → same container reference
3. `list.append()` is GIL-safe for concurrent writes
4. Parent reads accumulated data after all threads complete

Used by: `_batch_trace` (per-item trace events). Previously used by: `__llm_calls__` (removed). Reusable for: future cache hit tracking per batch item.

### Wrapper Chain Traversal

`_find_template_wrapper()` and `_find_batch_or_workflow_node()` traverse `inner_node` → `_inner_node` → `_wrapped` attribute chain. Pattern:
```python
current = self.inner_node
while current:
    if hasattr(current, "target_attribute"):
        return current
    for attr in ("inner_node", "_inner_node", "_wrapped"):
        if hasattr(current, attr):
            current = getattr(current, attr)
            break
    else:
        break
```
The `_get_actual_node_class()` method was the original example. Now three traversal methods follow this pattern.

### Child Collector for Sub-Workflows

When a cross-cutting concern needs visibility into sub-workflow execution:
1. Store reference in shared store (e.g., `_trace_collector`)
2. Add to `_PROPAGATED_KEYS` in `WorkflowExecutor`
3. In `WorkflowExecutor.exec()`, create a child instance
4. Pass child to `compile_ir_to_flow()`
5. After child completes, read results from child instance
6. Store on `self` for parent `InstrumentedNodeWrapper` to read via chain traversal

### Key Naming Convention

- `_single_underscore` for shared store keys (survives `_sanitize_for_json`)
- `__double_underscore__` for system state (`__execution__`, `__warnings__`) — filtered from traces and mutations
- Add new `_prefixed` keys to filter lists in `_sanitize_for_json()` and mutations computation if they shouldn't appear in traces

## Breaking Changes

### Trace Format 2.0.0

| Removed | Added |
|---------|-------|
| `shared_before` | `node_params` |
| `shared_after` | `template_resolutions` |
| `_filter_shared()` truncation | `node_output` |
| `_calculate_mutations()` value diff | `mutations` (key-set diff only) |
| `llm_prompt_truncated` / `llm_response_truncated` variants | `batch_items` (per-item events) |
| `save_to_file(llm_calls=...)` parameter | `sub_workflow_events` (child events) |
| | `cached` flag |

### `__llm_calls__` Removal

All code reading `shared["__llm_calls__"]` must migrate to `trace_collector.collect_llm_calls()`. The trace collector is always available via `shared["_trace_collector"]` or passed directly.

### CLI Changes

- `--report` flag added to workflow command
- `--report-dir` flag for custom output path
- `pflow trace report` subcommand added
- `allow_interspersed_args=True` — flags can appear before or after workflow argument

## Future Considerations

### Extension Points

- **Task 106 (Iteration Cache)**: `_handle_cached_execution()` already records `cached: true` trace events. Reports render `[cached]`. Cache system just needs to set up `shared[node_id]` with cached output and trigger the existing path.
- **MCP trace tool**: Stub exists (`# from . import trace_tools` in `tools/__init__.py`). Needs design for multi-file report access via single MCP response.
- **Batch item labeling**: Report uses `item-0/`, `item-1/`. Could use meaningful names from batch item data (heuristic or `label_field` config).

### Scalability Concerns

- No truncation means trace files grow with output size. A 233-LLM-call workflow could produce a 50MB+ trace. Acceptable for now (local temp files, no users), but may need configurable limits later.
- `_compute_event_cost()` is called per-event per-table-row during report generation. For large workflows, this is redundant recursive traversal. Could precompute once and pass as context.

## AI Agent Guidance

### Quick Start for Related Tasks

1. Read `src/pflow/runtime/wrappers/instrumented_wrapper.py` — this is the orchestration hub. `_run()` captures data, `_record_trace()` structures it, chain traversal methods read from other wrappers.
2. Read `src/pflow/runtime/workflow_trace.py` — `record_node_execution()` for the trace event schema, `_sanitize_for_json()` for key filtering rules, `collect_llm_calls()` for cost data access.
3. For report changes: `src/pflow/core/trace_report.py` — pure functions taking dicts, returning strings. Easy to test, easy to modify.

### Common Pitfalls

1. **`wrapper_attrs` in `TemplateAwareNodeWrapper`**: Any new `self.attribute` must be added to `wrapper_attrs` set, or `__setattr__` silently routes it to `self.inner_node`.
2. **`_sanitize_for_json` filtering**: Keys starting with `__` (except `__llm_calls__`, `__metrics__`) and `_trace`, `_debug`, `_batch_trace` are stripped. New shared store keys must not match these patterns (or be added to allowlists).
3. **`InstrumentedNodeWrapper.__deepcopy__`**: `self.trace` and `self.metrics` are shared by reference, NOT deep-copied. This is intentional for parallel batch items. Don't change this.
4. **Thread safety**: `list.append()` is GIL-safe. `dict.__setitem__` with integer keys is GIL-safe. Don't use more complex concurrent data structures — the existing pattern works.

### Test-First Recommendations

When modifying trace-related code, run these first:
```bash
uv run pytest tests/test_runtime/test_trace_integration.py -v  # Integration seams
uv run pytest tests/test_core/test_trace_report.py -v           # Report format
uv run pytest tests/test_integration/test_metrics_integration.py -v  # Cost chain
```

---

*Generated from implementation context of Task 108. Branch: feat/smart-trace-debug. 4346 tests passing.*
