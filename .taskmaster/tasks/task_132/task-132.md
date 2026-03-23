# Task 132: Unify LLM Data via Trace Collector (Remove `__llm_calls__`)

## Description

Replace the `__llm_calls__` shared store accumulator with the trace collector as the single source of truth for all LLM execution data (calls, tokens, cost, models). Currently LLM data flows through two parallel paths — `__llm_calls__` (shared mutable list) and trace events (`llm_call` field per event). This refactor eliminates the duplication.

## Status
not started

## Dependencies
- Task 108: Smart Trace Debug Output — the tree-structured trace with per-event `llm_call` fields must be complete and stable first

## Priority
low (cleanup/simplification — after Task 108 Phase 1 is stable)

## Context

### Current State (After Task 108)

LLM call data flows through **two parallel paths**:

1. **`__llm_calls__`** (shared store list): Each `InstrumentedNodeWrapper._capture_llm_usage()` appends `{model, tokens, cost, node_id}` to `shared["__llm_calls__"]`. Propagated to sub-workflows via `_PROPAGATED_KEYS`. GIL-protected `list.append()` for parallel batch items. Used by MetricsCollector, CLI cost display, execution formatters, and `save_to_file(llm_calls=...)`.

2. **Trace events** (`llm_call` field): Each trace event has an `llm_call` dict with the same data. Tree-structured — batch items and sub-workflow events contain nested `llm_call` fields. `_collect_llm_summary()` recursively scans the tree.

These contain the same information but serve different consumers. After Task 108, the trace collector has complete data via its tree structure, making `__llm_calls__` redundant.

### What This Task Does

- Remove `__llm_calls__` from shared store initialization
- Remove `__llm_calls__` from `_PROPAGATED_KEYS`
- Remove `_capture_llm_usage()` / `_capture_item_llm_usage()` methods
- Update MetricsCollector to read from trace collector instead
- Update CLI cost display (`format_execution_success()`, `_display_execution_summary()`) to read from trace collector
- Update `save_to_file()` to always use `_collect_llm_summary()` (remove `llm_calls` parameter)
- Remove `__llm_calls__` from `_sanitize_for_json()` allowlist

### Benefits

- **Single source of truth** — trace collector owns all LLM data
- **Simpler shared store** — one less system key to manage
- **No GIL-dependent pattern** — removes the shared mutable list pattern for parallel batch items (trace events use per-item collectors instead)
- **Cleaner code** — removes `_capture_llm_usage()`, `_capture_item_llm_usage()`, and the `llm_calls` parameter threading

### Risks

- MetricsCollector needs access to the trace collector (currently it doesn't — they're independent collectors)
- If `--no-trace` is used, there's no trace collector, so LLM data would be unavailable for cost display. Would need either: (a) always create a trace collector (even without saving), or (b) keep a lightweight LLM accumulator as fallback
- Formatting code in `execution/formatters/` reads from `__llm_calls__` — need to update all consumers

## Scope

### In Scope
- Remove `__llm_calls__` accumulator from shared store
- Update all consumers to read from trace collector
- Handle `--no-trace` case (lightweight collector or always-create pattern)

### Out of Scope
- Changing the trace format (already done in Task 108)
- Removing LLM interception (separate concern — captures prompts)

## Related
- Task 108: Smart Trace Debug Output (prerequisite)
- Task 106: Iteration Cache (may also benefit from unified data source)
