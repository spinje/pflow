# Feature: unified_metrics_tracing

## Objective

Collect cost metrics for pflow execution transparently.

## Requirements

- Must track LLM token usage across all nodes
- Must calculate costs based on model pricing
- Must capture execution timing per node
- Must support both lightweight metrics and detailed tracing
- Must maintain zero overhead when disabled
- Must output Claude Code-compatible JSON format

## Scope

- Does not implement cost budgets or limits
- Does not provide historical metrics storage
- Does not support distributed tracing
- Does not include visualization tools
- Does not handle non-LLM costs

## Inputs

- output_format: str - Output format ("text" or "json")
- trace: bool - Enable workflow execution tracing (new behavior)
- trace_planner: bool - Enable planner execution tracing (new flag)
- workflow_ir: dict[str, Any] - Workflow intermediate representation
- shared_storage: dict[str, Any] - Shared execution context

## Outputs

Returns: dict - JSON output with metrics when output_format="json"

Side effects:
- Creates trace files in ~/.pflow/debug/ when tracing enabled
- Modifies shared_storage with __metrics__ key during execution
- Modifies shared_storage with __llm_calls__ list for accumulation
- Wraps nodes with InstrumentedNodeWrapper during compilation

## Structured Formats

```json
{
  "output_structure": {
    "result": {},
    "is_error": false,
    "duration_ms": 0,
    "duration_planner_ms": null,
    "total_cost_usd": 0.0,
    "num_nodes": 0,
    "metrics": {
      "planner": {},
      "workflow": {},
      "total": {}
    }
  },
  "trace_file_structure": {
    "workflow_id": "string",
    "start_time": "ISO8601",
    "duration_ms": 0,
    "nodes": [
      {
        "node_id": "string",
        "node_type": "string",
        "duration_ms": 0,
        "shared_before": {},
        "shared_after": {},
        "template_resolutions": {},
        "llm_call": {},
        "success": true,
        "error": null
      }
    ]
  }
}
```

## State/Flow Changes

- None

## Constraints

- MetricsCollector instance lifetime = single execution
- InstrumentedNodeWrapper must be outermost wrapper
- Trace files must be valid JSON
- Model pricing must be hardcoded (no external config in MVP)

## Rules

1. If output_format != "json" then do not create MetricsCollector
2. If output_format == "json" then create MetricsCollector
3. If trace == true then create WorkflowTraceCollector
4. If trace_planner == true then enable planner TraceCollector
5. InstrumentedNodeWrapper captures timing using time.perf_counter()
6. InstrumentedNodeWrapper monitors shared["llm_usage"] after node execution
7. InstrumentedNodeWrapper appends LLM usage to shared["__llm_calls__"] list
8. MetricsCollector aggregates from shared["__llm_calls__"] list
9. MetricsCollector calculates cost using MODEL_PRICING dictionary
10. JSON output includes is_error at root level
11. JSON output includes duration_ms at root level
12. JSON output includes duration_planner_ms at root level
13. JSON output includes total_cost_usd at root level
14. JSON output includes num_nodes at root level
15. Trace files capture shared store before each node
16. Trace files capture shared store after each node
17. Trace files must capture template resolutions from TemplateAwareNodeWrapper
18. Trace files include error details for failed nodes
19. Trace files include all nodes executed before failure
20. WorkflowTraceCollector saves to ~/.pflow/debug/workflow-{timestamp}.json
21. Planner TraceCollector saves to ~/.pflow/debug/planner-{timestamp}.json
22. Timestamp format is YYYYMMDD-HHMMSS
23. UUID stored inside trace JSON as execution_id field

## Edge Cases

- No LLM nodes in workflow → total_cost_usd = 0.0
- Unknown model in llm_usage → use default pricing
- Missing llm_usage in shared → skip token tracking for that node
- Node execution fails → still capture timing and partial metrics
- Trace file write fails → log error to stderr but continue
- output_format == "json" but execution fails → include metrics with error
- Both trace flags enabled → generate two separate trace files

## Error Handling

- Node wrapper attribute access fails → delegate to wrapped node via __getattr__
- Cost calculation for unknown model → use gpt-4o-mini pricing as default
- Trace file directory creation fails → log warning and skip trace
- JSON serialization of trace fails → fallback to string representation

## Non-Functional Criteria

- Metrics collection overhead < 1% of execution time
- Trace file size < 10MB for typical workflows
- Zero memory leaks from wrapper references

## Examples

### Workflow execution with metrics
```json
{
  "result": {"analysis": "complete"},
  "is_error": false,
  "duration_ms": 3521,
  "duration_planner_ms": null,
  "total_cost_usd": 0.0127,
  "num_nodes": 4,
  "metrics": {
    "workflow": {
      "duration_ms": 3521,
      "nodes_executed": 4,
      "cost_usd": 0.0127
    }
  }
}
```

### Natural language with planner + workflow
```json
{
  "result": {"story": "..."},
  "is_error": false,
  "duration_ms": 13968,
  "duration_planner_ms": 5234,
  "total_cost_usd": 0.0968,
  "num_nodes": 11,
  "metrics": {
    "planner": {"cost_usd": 0.0734},
    "workflow": {"cost_usd": 0.0234},
    "total": {"cost_usd": 0.0968}
  }
}
```

## Test Criteria

1. output_format="text" → no MetricsCollector created
2. output_format="json" → MetricsCollector created
3. trace=true → WorkflowTraceCollector created
4. trace_planner=true → planner TraceCollector enabled
5. Node execution → timing captured with perf_counter
6. LLM node execution → llm_usage monitored
7. LLM node execution → usage appended to __llm_calls__ list
8. Multiple LLM calls → all entries in __llm_calls__ list
9. MetricsCollector → aggregates from __llm_calls__ list
10. Known model → correct cost calculated
11. JSON output → is_error field present
12. JSON output → duration_ms field present
13. JSON output → duration_planner_ms field present
14. JSON output → total_cost_usd field present
15. JSON output → num_nodes field present
16. Trace enabled → shared_before captured
17. Trace enabled → shared_after captured
18. Template node → resolutions captured
19. Node fails → error details in trace
20. Workflow fails → all prior nodes in trace
21. Workflow trace → saved to workflow-{timestamp}.json
22. Planner trace → saved to planner-{timestamp}.json
23. Trace file → contains execution_id UUID field
24. Timestamp format → YYYYMMDD-HHMMSS
25. No LLM nodes → cost = 0.0
26. Unknown model → default pricing used
27. Missing llm_usage → node skipped in aggregation
28. Failed node → timing still captured
29. Trace write fails → stderr warning logged
30. JSON with error → metrics still included
31. Both traces → two files generated

## Notes (Why)

- Top-level metrics enable quick access without nested navigation
- Claude Code compatibility allows direct performance comparison
- Unified wrapper minimizes overhead versus separate metrics/tracing wrappers
- Complete error traces enable debugging of failure sequences
- Hardcoded pricing avoids external dependencies in MVP

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1                          |
| 2      | 2                          |
| 3      | 3                          |
| 4      | 4                          |
| 5      | 5                          |
| 6      | 6                          |
| 7      | 7                          |
| 8      | 8, 9                       |
| 9      | 10                         |
| 10     | 11                         |
| 11     | 12                         |
| 12     | 13                         |
| 13     | 14                         |
| 14     | 15                         |
| 15     | 16                         |
| 16     | 17                         |
| 17     | 18                         |
| 18     | 19                         |
| 19     | 20                         |
| 20     | 21                         |
| 21     | 22                         |
| 22     | 24                         |
| 23     | 23                         |

## Versioning & Evolution

- v1.0.0 — Initial unified metrics and tracing system

## Epistemic Appendix

### Assumptions & Unknowns

- Verified: llm library response has usage() method (not property) that returns object with .input/.output attributes
- Verified: time.perf_counter() available and already used in TimedResponse class
- Unknown exact token counts for models that don't report usage (fallback to empty dict)
- Template resolution capture requires new implementation (currently only logged)

### Conflicts & Resolutions

- Current --trace flag traces planner only. Resolution: --trace for workflows, --trace-planner for planner
- Code uses time.time() not time.perf_counter(). Resolution: Standardize to time.perf_counter()
- llm_usage overwrites not accumulates. Resolution: Add __llm_calls__ list for accumulation
- Trace directory is ~/.pflow/debug/ not ~/.pflow/traces/. Resolution: Keep existing directory
- Trace filenames use timestamp not UUID. Resolution: Keep timestamp format, UUID inside JSON

### Decision Log / Tradeoffs

- Chose unified wrapper over separate metrics/tracing wrappers for reduced overhead
- Chose hardcoded pricing over config file for MVP simplicity
- Chose top-level metrics over nested-only for better UX
- Chose complete error traces over error-only traces for better debugging
- Chose per-million token pricing units to match existing test tool implementation
- Chose to keep existing ~/.pflow/debug/ directory over creating new ~/.pflow/traces/
- Chose to accumulate LLM usage in list over modifying LLMNode behavior

### Ripple Effects / Impact Map

- CLI must be modified to handle new flags
- Compiler must apply InstrumentedNodeWrapper
- JSON output handler must wrap results with metrics
- Existing DebugWrapper must integrate MetricsCollector

### Residual Risks & Confidence

- Risk: Wrapper overhead exceeds 1% target. Mitigation: performance tests. Confidence: High
- Risk: Unknown models cause cost calculation errors. Mitigation: default pricing. Confidence: High
- Risk: Large workflows generate huge trace files. Mitigation: 10MB warning. Confidence: Medium

### Epistemic Audit (Checklist Answers)

1. Verified llm usage structure and wrapper delegation patterns from actual code
2. Incorrect time.time() usage would reduce precision but not break functionality
3. Prioritized robustness with fallback pricing and empty dict for missing usage
4. All 23 rules mapped to 31 test criteria
5. Touches CLI, compiler, runtime, debug module, and output handling
6. Template resolution capture needs new implementation. Confidence: High after verification