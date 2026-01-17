# Task 32: Unified Metrics and Tracing System for Workflow Execution

## Description
Implement a comprehensive observability system that provides cost tracking, performance metrics, and debugging capabilities for both planner and workflow execution. The system collects lightweight metrics when using `--output-format json` and detailed traces with `--trace` flags, giving users complete visibility into LLM costs and execution performance.

## Status
done

## Completed
2025-08-30

## Dependencies
- Task 27: Planner Debugging Capabilities - Builds upon the DebugWrapper and tracing infrastructure, reuses patterns for LLM interception and trace collection
- Task 24: Workflow Manager - Integrates with workflow loading and execution to track metrics
- Task 18: Template Variable System - Must capture template resolution visibility in traces
- Task 9: Automatic Namespacing - Must trace through namespace wrappers correctly

## Priority
high

## Details
The unified metrics and tracing system addresses critical observability gaps in pflow by providing transparent cost tracking and performance insights while maintaining zero overhead for default execution.

### Core Problems Being Solved
1. **No cost visibility**: Users don't know how much their LLM calls cost
2. **No workflow debugging**: Can't see what happens during workflow execution (unlike planner which has tracing)
3. **No performance metrics**: Can't identify bottlenecks or optimization opportunities
4. **Hidden template resolution**: Can't see what `${variable}` becomes during execution
5. **No aggregated metrics**: Token usage overwrites on each LLM call instead of accumulating

### Architecture Overview
The system uses a single `InstrumentedNodeWrapper` that serves both metrics collection (lightweight, always with JSON output) and tracing (detailed, opt-in with flags). This unified approach minimizes overhead and ensures consistent data between systems.

### Key Design Decisions
1. **Top-level metrics in JSON**: Claude Code-compatible format with `is_error`, `duration_ms`, `total_cost_usd` at root level for easy access
2. **Unified wrapper pattern**: Single instrumentation point for both metrics and tracing to avoid duplicate overhead
3. **Progressive enhancement**: No flags = zero overhead, `--output-format json` = metrics, `--trace` = full debugging
4. **Complete error traces**: Trace files include all execution data up to and including errors, not just error information
5. **Flag restructuring**: `--trace` for workflows, `--trace-planner` for planner (no backward compatibility needed in private MVP)

### Implementation Components

#### MetricsCollector (`src/pflow/core/metrics.py`)
- Lightweight aggregator for operational metrics
- Tracks timing, token usage, costs across planner and workflow
- Always active when `--output-format json` is used
- Calculates costs based on model pricing

#### InstrumentedNodeWrapper (`src/pflow/runtime/instrumented_wrapper.py`)
- Unified wrapper applied to all workflow nodes during compilation
- Captures timing for every node execution
- Monitors `shared["llm_usage"]` for token tracking
- Optionally captures detailed traces when trace collector present
- Applied as outermost wrapper: Instrumented → Namespaced → TemplateAware → BaseNode

#### WorkflowTraceCollector (`src/pflow/runtime/workflow_trace.py`)
- Captures detailed execution data for debugging
- Records shared store mutations before/after each node
- Tracks template resolutions (what `${variable}` became)
- Captures full LLM prompts and responses
- Saves to `~/.pflow/traces/workflow-{id}.json`

### JSON Output Format
```json
{
  "result": {...},              // Actual workflow output
  "is_error": false,            // Quick error check
  "duration_ms": 13968,         // Total time
  "duration_planner_ms": 5234,  // Planning overhead (null if no planner)
  "total_cost_usd": 0.0968,     // Combined LLM costs
  "num_nodes": 11,              // Total nodes executed
  "metrics": {                  // Detailed breakdown
    "planner": {...},           // Only if planner was used
    "workflow": {...},          // Always present
    "total": {...}              // Aggregated totals
  }
}
```

### CLI Flag Changes
- `--trace`: Traces workflow execution (new behavior)
- `--trace-planner`: Traces planner execution (replaces current `--trace` for natural language)
- No deprecation warnings needed since project is private/in development

### Integration Points
1. **Planner**: Enhance existing DebugWrapper to use MetricsCollector
2. **Compiler**: Apply InstrumentedNodeWrapper during node instantiation in `_create_single_node()`
3. **CLI**: Create MetricsCollector when `--output-format json`, pass through execution pipeline
4. **JSON Output**: Modify `_handle_json_output()` to include top-level metrics

## Test Strategy
Comprehensive testing will ensure the metrics system works correctly without impacting performance:

### Unit Tests
- MetricsCollector aggregation and cost calculation
- InstrumentedNodeWrapper timing and data capture
- Token extraction from various LLM response formats
- Cost calculation for different models

### Integration Tests
- End-to-end metrics collection for planner + workflow execution
- Trace file generation and content verification
- JSON output format with top-level metrics
- Error scenarios still collecting partial metrics
- Multi-layer wrapper compatibility

### Performance Tests
- Verify zero overhead when no flags are used
- Measure impact of metrics collection (should be <1%)
- Ensure trace file sizes are reasonable

### Key Test Scenarios
- Workflow with multiple LLM nodes (aggregation)
- Failed workflow (partial metrics + error details)
- Template resolution tracking in traces
- Path A vs Path B detection in planner metrics
- Natural language with both `--trace` and `--trace-planner`
