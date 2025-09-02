# Task 32 Review: Unified Metrics and Tracing System for Workflow Execution

## Executive Summary
Implemented a zero-overhead observability system providing cost tracking and debugging capabilities through progressive enhancement. The system uses a single InstrumentedNodeWrapper serving both lightweight metrics (JSON output) and detailed tracing (debug files), with critical fixes for LLM usage accumulation and planner metrics continuity.

## Implementation Overview

### What Was Built
Created three core modules (`MetricsCollector`, `InstrumentedNodeWrapper`, `WorkflowTraceCollector`) integrated across planner, compiler, and CLI layers. The system captures LLM costs, execution timing, and debugging traces without overhead when disabled. Major deviation from spec: Had to solve the LLM usage overwrite problem with an accumulation list pattern (`__llm_calls__`) since modifying existing nodes wasn't viable.

### Implementation Approach
Unified telemetry architecture treating metrics and tracing as the same data at different verbosity levels. Single wrapper serves both needs, applied as outermost layer to capture all operations. Used `time.perf_counter()` throughout for monotonic high-resolution timing. Intercepted LLM library directly for planner prompt capture.

## Files Modified/Created

### Core Changes
- `src/pflow/core/metrics.py` - MetricsCollector with per-million token pricing and aggregation
- `src/pflow/runtime/instrumented_wrapper.py` - Unified wrapper handling both metrics and tracing
- `src/pflow/runtime/workflow_trace.py` - Detailed trace collector with shared store snapshots
- `src/pflow/planning/debug.py` - Enhanced DebugWrapper to accept metrics, modified TimedResponse for lazy evaluation
- `src/pflow/runtime/compiler.py` - Modified _create_single_node to apply InstrumentedNodeWrapper as outermost
- `src/pflow/cli/main.py` - Added --trace-planner flag, enhanced JSON output structure, metrics threading

### Test Files
- `tests/test_core/test_metrics.py` - 15 tests for cost aggregation (CRITICAL for pricing accuracy)
- `tests/test_runtime/test_instrumented_wrapper.py` - 33 tests for delegation patterns (CRITICAL for wrapper compatibility)
- `tests/test_runtime/test_workflow_trace.py` - 26 tests for trace generation
- `tests/test_integration/test_metrics_integration.py` - End-to-end metrics flow testing

## Integration Points & Dependencies

### Incoming Dependencies
- CLI → MetricsCollector (via execute_json_workflow)
- Compiler → InstrumentedNodeWrapper (wraps every node when collectors present)
- Planner → DebugWrapper → MetricsCollector (for planner cost tracking)
- JSON output handler → MetricsCollector.get_summary() (for output formatting)

### Outgoing Dependencies
- InstrumentedNodeWrapper → NamespacedNodeWrapper → TemplateAwareNodeWrapper → BaseNode (wrapper chain)
- MetricsCollector → MODEL_PRICING dictionary (for cost calculation)
- WorkflowTraceCollector → ~/.pflow/debug/ directory (for trace files)
- Both collectors → shared["__llm_calls__"] list (for LLM usage accumulation)

### Shared Store Keys
- `__llm_calls__` - List of LLM usage dicts with node_id, tokens, model, is_planner flags
- `__is_planner__` - Boolean flag marking planner execution context
- `llm_usage` - Original LLM node output (read but not modified)
- `node_id/llm_usage` - Namespaced LLM usage location (critical discovery)

## Architectural Decisions & Tradeoffs

### Key Decisions
- **Accumulation list over modification** → Can't modify nodes, so accumulate in parallel list → Preserves node purity
- **Outermost wrapper position** → Must see all operations including namespacing → Alternative (inner wrapper) would miss data
- **Unified wrapper vs separate** → Single instrumentation point → Rejected dual wrappers for complexity
- **Per-million token pricing** → Matches existing test patterns → Alternative per-token would need float precision
- **Metrics collector threading** → Pass through execution chain → Creating new collector loses planner metrics

### Technical Debt Incurred
- Template resolution capture still TODO - only logged at DEBUG level
- Some LLM models use default pricing when not in dictionary
- Trace files can grow large with big workflows (no streaming)
- No mechanism to disable specific metrics while keeping others

## Testing Implementation

### Test Strategy Applied
Created tests from scratch (zero existing coverage for debug system). Focused on behavior over implementation - test that costs accumulate correctly, not internal data structures. Used test-writer-fixer subagent for all test creation.

### Critical Test Cases
- `test_multiple_llm_calls_accumulate_costs` - Verifies the accumulation pattern works
- `test_wrapper_delegation_pattern` - Ensures pickle/copy compatibility
- `test_namespace_interaction` - Confirms metrics capture through namespacing
- `test_planner_metrics_passed_through` - Validates metrics collector continuity

## Unexpected Discoveries

### Gotchas Encountered
1. **LLM usage overwrites** - Each node sets `shared["llm_usage"]` replacing previous
2. **Lazy response evaluation** - `model.prompt()` returns instantly, API call happens on `.json()`
3. **Namespacing redirects writes** - `shared["llm_usage"]` becomes `shared[node_id]["llm_usage"]`
4. **Planner/workflow isolation** - Separate shared stores, metrics must bridge them
5. **Test infrastructure blocker** - Integration tests block planner imports preventing combined testing

### Edge Cases Found
- Empty `__llm_calls__` list initialization required in planner shared store
- Usage data only available AFTER response consumption, not before
- Wrapper __getattr__ must exclude pickle methods to prevent recursion
- Trace files need sanitized workflow names to avoid filesystem issues

## Patterns Established

### Reusable Patterns
```python
# LLM usage accumulation pattern
if "__llm_calls__" not in shared:
    shared["__llm_calls__"] = []
llm_call_data = {**usage, "node_id": node_id, "is_planner": is_planner}
shared["__llm_calls__"].append(llm_call_data)

# Wrapper delegation pattern
def __getattr__(self, name: str) -> Any:
    if name in ("__setstate__", "__getstate__", "__getnewargs__", "__getnewargs_ex__"):
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
    inner = object.__getattribute__(self, "inner_node")
    return getattr(inner, name)

# Check both root and namespaced locations
llm_usage = shared.get("llm_usage") or shared.get(self.node_id, {}).get("llm_usage")
```

### Anti-Patterns to Avoid
- Don't use `time.time()` - always `time.perf_counter()` for timing
- Don't assume `shared["llm_usage"]` accumulates - it overwrites
- Don't create new MetricsCollector mid-flow - loses previous metrics
- Don't put InstrumentedNodeWrapper inside other wrappers - must be outermost

## Breaking Changes

### API/Interface Changes
- JSON output structure changed: `{"result": {...}, "is_error": false, "duration_ms": ..., "metrics": {...}}`
- New CLI flags: `--trace-planner` added, `--trace` repurposed for workflows only
- DebugContext now accepts optional metrics_collector parameter

### Behavioral Changes
- JSON output always includes metrics when `--output-format json` used
- Trace files saved to `~/.pflow/debug/` with new naming: `planner-trace-*.json`, `workflow-trace-*.json`
- All LLM costs now tracked (previously lost due to overwriting)

## Future Considerations

### Extension Points
- Template resolution capture hook point exists but needs implementation
- Metrics filtering could be added to MetricsCollector
- Streaming trace writes for large workflows
- Cost budgets/limits could hook into MetricsCollector

### Scalability Concerns
- Trace files grow linearly with workflow size
- `__llm_calls__` list unbounded (could add rotation)
- No metrics aggregation across multiple workflow runs

## AI Agent Guidance

### Quick Start for Related Tasks
1. Read `src/pflow/runtime/instrumented_wrapper.py` first - shows the wrapper pattern
2. Check wrapper order in `compiler.py:334-356` - critical for data visibility
3. Study `__llm_calls__` accumulation in `instrumented_wrapper.py:94-115`
4. Review metrics threading in `cli/main.py:1088-1167` for continuity pattern

### Common Pitfalls
- Forgetting to check namespaced location for data (`shared[node_id][key]`)
- Creating wrapper without delegation pattern causes pickle failures
- Timing before response consumption misses actual API call duration
- Not passing metrics collector through call chain loses data
- Assuming test infrastructure allows planner+workflow combination

### Test-First Recommendations
1. Run `pytest tests/test_core/test_metrics.py` - verify cost calculations
2. Run `pytest tests/test_runtime/test_instrumented_wrapper.py` - check wrapper behavior
3. Write test for LLM accumulation before modifying
4. Test with both namespacing enabled and disabled
5. Verify JSON output structure matches Claude Code expectations

## Implementer ID

These changes was made with Claude Code with Session ID: `be131375-e3d6-4359-9f9b-25d69c759c64`

## PR URL
https://github.com/spinje/pflow/pull/10

---